# Apple Screen Sharing on macOS

An OS-hosted VNC server for vncdotool to test against on a macOS machine (a
GitHub `macos-latest` runner in CI). `tests/functional/test_os_servers.py`
runs the same connect/type/capture round trip used for the Docker servers,
and `collect-diagnostics.sh` gathers the evidence when something goes wrong.

## Where the setup lives

In `.github/actions/os-server`: `action.yml` wires the inputs,
`screen-sharing.sh` does the work, and `require-disposable-host.sh` decides
whether the machine may be changed at all.

Enabling Remote Management turns the machine it runs on into an unattended
remote-control target, and deleting the checkout does not switch it back
off. So `screen-sharing.sh` calls the host check immediately before that
step: `CI`, `GITHUB_ACTIONS`, `RUNNER_ENVIRONMENT=github-hosted` and
`GITHUB_RUN_ID` together, which also keeps it off a *self-hosted* runner —
someone's real machine. To exercise the setup by hand, use a virtual machine
you are willing to delete, that auto-logs in, and set
`VNCDOTOOL_OS_SERVER_DISPOSABLE_HOST` to `yes-destroy-this-machine`.

Everything before that check only reads, which is why it is not at the top of
the file: knowing which account to authenticate as is useful to run anywhere,
and on a machine without auto-login it is also where the script stops.

Against a server that is already up — a runner mid-job, or that VM — the
tests are just:

```sh
uv run python -m unittest discover -v -s tests/functional -t . -p 'test_os_servers.py'
```

## What the setup has to get right

* **Authentication is ARD/Diffie-Hellman (security type 30), with a
  username.** vncdotool's existing ARD support handles the whole round trip;
  the server is reached as a local user the setup action creates.

* **The legacy VNC password is dead.** `kickstart -setvnclegacy -vnclegacy
  yes -setvncpw` is accepted silently on current macOS, but the server still
  demands ARD auth afterwards. Don't reach for it as a way to avoid needing
  a username.

* **It answers input slowly.** A key event took over five seconds to be
  acknowledged on a hosted runner, where a container answers in
  milliseconds. `vncservers.py` therefore gives OS-hosted servers a much
  longer per-request timeout (`VNCDOTOOL_OS_SERVER_TIMEOUT`, 60s).

* **Screen Sharing is socket-activated on 5900.** Nothing has to be started
  beyond `kickstart -activate`; waiting for the port is enough.

## The first login costs a minute

Authenticating as a user who is not the one holding `/dev/console` makes
Screen Sharing fast-user-switch to that account, and on a runner where it
has never logged in before that is a full first login. Two runs measured
the same shape: `UserAccountUpdater` alone ran 28s and 33s, Setup Assistant
("MiniBuddy") launched after it, and `loginwindow` never reached
`LoginComplete` — the session was still churning a minute later, which is
also why the framebuffer came back black.

The cost is not confined to the connection that triggers it. Screen Sharing
exits a few seconds after its last viewer leaves (`No viewers so time to
exit`), so the next `vncdo` starts the whole thing again, and in run
[32386264568](https://github.com/sibson/vncdotool/actions/runs/32386264568)
that landed the delay inside the test step instead of the readiness step:
60s of nothing between the two.

Authenticating as the console owner (`runner`) sidesteps all of that by
attaching to a session that is already logged in. Its password cannot be
*set* — the account holds a secure token, and both tools refuse:

* `sysadminctl -resetPasswordFor runner -newPassword ...` prints `Operation
  is not permitted without secure token unlock`, changes nothing, and
  **exits 0** (run
  [32409282119](https://github.com/sibson/vncdotool/actions/runs/32409282119),
  where the lie surfaced as nine `Authentication or authorization failure`
  readiness attempts three minutes later).
* `sudo dscl . -passwd /Users/runner ...` answers `DS Error: -14090
  (eDSAuthFailed)` and asks for the old password (run
  [32409927196](https://github.com/sibson/vncdotool/actions/runs/32409927196)).

It does not need to be set, though: it can be read. These images enable GUI
auto-login ([configure-autologin.sh][autologin]), and auto-login means
`loginwindow` has to be able to replay the password, so macOS keeps it in
`/etc/kcpassword` XORed against a fixed 11-byte key rather than hashed.
`runner` logging itself in at boot, which `who` shows in every diagnostics
artifact, is the proof that file matches the live password.

So the setup decodes it, masks it, and gates it on `dscl . -authonly` before
using it. That took the macOS job from 2m37 to 33s: no user switch, no
login, readiness satisfied on the first attempt, the tests themselves in
under four seconds.

It does not fall back, and there is no path that creates an account. Anything
unexpected — no file, a format change (that has happened:
[runner-images#5231][5231] shipped a kcpassword written as UTF-8 rather than
raw bytes), a password that does not authenticate — fails the job. A fallback
would quietly restore the slow path and hide the day the image changes, which
is exactly the day we want to hear about it.

It also makes the setup safe to run by accident. A machine that does not
auto-login has no `/etc/kcpassword`, so there is nothing to authenticate as
and the script stops before it touches anything — which is every developer
machine, since auto-login is off by default. The host check below still
guards what comes after, because switching Remote Management on is a change
a checkout deletion does not undo.

[autologin]: https://github.com/actions/runner-images/blob/main/images/macos/scripts/build/configure-autologin.sh
[5231]: https://github.com/actions/runner-images/issues/5231

## Readiness

An open RFB port is not readiness here, and neither is a per-request
timeout. Screen Sharing is socket-activated, so the first connection is
what starts the server -- and that connection sometimes never finishes its
handshake, while the very next one succeeds in seconds. A test that opened
the first connection failed with a timeout after two minutes, and the
screenshot step immediately afterwards captured fine.

So the setup action waits for the port, and CI then runs
`tests/functional/wait_for_servers.py os`, which retries whole connections
until one completes an RFB round trip. Only then do the tests run, and a
timeout inside a test means something real.

## What it proves, and what it doesn't

Connect, RFB handshake, ARD authentication and key events all work. The
framebuffer, however, comes back fully black, and that is the runner having
no display rather than anything about which account we use. Attaching to
the console owner's live, logged-in session — no `loginwindow`, no Setup
Assistant — still captures `1 colours`, which rules out the theory that we
were photographing a session stuck mid-login. So `vncservers.py` marks this
server `renders_desktop=False` and the test asserts the protocol round trip
without asserting pixels.
