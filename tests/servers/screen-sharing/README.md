# Apple Screen Sharing on macOS

An OS-hosted VNC server for vncdotool to test against on a macOS machine (a
GitHub `macos-latest` runner in CI). `tests/functional/test_server_compat_native.py`
runs the same connect/type/capture round trip used for the Docker servers,
and `collect-diagnostics.sh` gathers the evidence when something goes wrong.

The setup is `.github/actions/os-server`. Against a server already up, the
tests are:

```sh
uv run python -m unittest discover -v -s tests/functional -t . -p 'test_server_compat_native.py'
```

## What the setup has to get right

* **Authenticate as the console owner.** Any other account makes Screen
  Sharing fast-user-switch into that account's first login, which took a
  minute of the job and left the session at `loginwindow`. The console
  owner's session is already up.

* **Read that account's password, don't set it.** It holds a secure token,
  so `sysadminctl` fails while exiting 0 and `dscl` returns `eDSAuthFailed`.
  GitHub's images enable auto-login ([configure-autologin.sh][autologin]),
  which means macOS keeps the password in `/etc/kcpassword` XORed against a
  fixed 11-byte key, and `who` shows the account logging itself in at boot.

* **Refuse anything that doesn't decode to a printable password.**
  [runner-images#5231][5231] once shipped kcpassword written as UTF-8 rather
  than raw bytes.

* **Authentication is ARD/Diffie-Hellman (security type 30), with a
  username.** vncdotool's existing ARD support handles the whole round trip.

* **The legacy VNC password is dead.** `kickstart -setvnclegacy -vnclegacy
  yes -setvncpw` is accepted silently on current macOS, but the server still
  demands ARD auth afterwards. Don't reach for it as a way to avoid needing
  a username.

* **It answers input slowly.** A key event took over five seconds to be
  acknowledged on a hosted runner, where a container answers in
  milliseconds. `utils.py` therefore gives OS-hosted servers a much
  longer per-request timeout (`VNCDOTOOL_OS_SERVER_TIMEOUT`, 60s).

* **Screen Sharing is socket-activated on 5900.** Nothing has to be started
  beyond `kickstart -activate`; waiting for the port is enough.

[autologin]: https://github.com/actions/runner-images/blob/main/images/macos/scripts/build/configure-autologin.sh
[5231]: https://github.com/actions/runner-images/issues/5231

## Running it anywhere but a hosted runner

`macos.sh` refuses unless `RUNNER_ENVIRONMENT=github-hosted`:
switching Remote Management on outlives both the job and the checkout, and a
self-hosted runner is someone's real machine. Nothing before that check
changes anything, and a machine that does not auto-login has no
`/etc/kcpassword` to read, so a developer machine stops on its own.

## Readiness

An open RFB port is not readiness here, and neither is a per-request
timeout. Screen Sharing is socket-activated, so the first connection is
what starts the server -- and that connection sometimes never finishes its
handshake, while the very next one succeeds in seconds. A test that opened
the first connection failed with a timeout after two minutes, and the
screenshot step immediately afterwards captured fine.

So the setup waits for the port, and CI then runs
`tests/functional/wait_for_servers.py os`, which retries whole connections
until one completes an RFB round trip. Only then do the tests run, and a
timeout inside a test means something real.

## What it proves, and what it doesn't

Connect, RFB handshake, ARD authentication and key events all work. The
framebuffer comes back fully black: the runner has no display, and
attaching to the console owner's live session captures `1 colours` too. So
`utils.py` marks this server `renders_desktop=False` and the test
asserts the protocol round trip without asserting pixels.
