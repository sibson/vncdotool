# Apple Screen Sharing on macOS

An OS-hosted VNC server for vncdotool to test against on a macOS machine (a
GitHub `macos-latest` runner in CI). `tests/functional/test_os_servers.py`
runs the same connect/type/capture round trip used for the Docker servers,
and `collect-diagnostics.sh` gathers the evidence when something goes wrong.

## There is no setup script

Enabling Remote Management turns the machine it runs on into an unattended
remote-control target, reachable with a password published in this
repository, and deleting the checkout afterwards leaves the account and the
setting behind. So the setup lives in a composite action,
`.github/actions/os-server`, whose steps only the Actions runner can
execute. There is deliberately nothing here to run against a laptop.

A composite action still runs on a *self-hosted* runner, which is someone's
real machine, so the action's first step asks the host to prove it is
disposable: `CI`, `GITHUB_ACTIONS`, `RUNNER_ENVIRONMENT=github-hosted` and
`GITHUB_RUN_ID` together. To exercise the setup by hand, use a virtual
machine you are willing to delete and set
`VNCDOTOOL_OS_SERVER_DISPOSABLE_HOST` to `yes-destroy-this-machine`.

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

Authenticating as the console owner (`runner`) would sidestep all of that by
attaching to a session that is already logged in — but ARD checks a real
account password, and that account's cannot be set. Both tools refuse,
because `runner` holds a secure token:

* `sysadminctl -resetPasswordFor runner -newPassword ...` prints `Operation
  is not permitted without secure token unlock`, changes nothing, and
  **exits 0** (run
  [32409282119](https://github.com/sibson/vncdotool/actions/runs/32409282119),
  where the lie surfaced as nine `Authentication or authorization failure`
  readiness attempts three minutes later).
* `sudo dscl . -passwd /Users/runner ...` answers `DS Error: -14090
  (eDSAuthFailed)` and asks for the old password (run
  [32409927196](https://github.com/sibson/vncdotool/actions/runs/32409927196)).

So the dedicated user stays, and the first login is a cost this job pays.
The setup does a `dscl . -authonly` after setting the password: whatever
tool sets it, a password that does not authenticate should fail the setup
step in a second rather than a readiness budget later.

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
framebuffer, however, comes back fully black. The reason looks like the
first login above rather than a runner with no display: what gets
photographed is a session still sitting at `loginwindow`. So
`vncservers.py` marks this server `renders_desktop=False` and the test
asserts the protocol round trip without asserting pixels; whether a
completed login renders anything is the open question behind that.
