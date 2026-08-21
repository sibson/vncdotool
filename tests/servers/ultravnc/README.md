# UltraVNC on Windows

An OS-hosted VNC server for vncdotool to test against on a Windows machine
(a GitHub `windows-latest` runner in CI). `tests/functional/test_os_servers.py`
runs the same connect/type/capture round trip used for the Docker servers,
and `collect-diagnostics.ps1` gathers the evidence when something goes wrong.

The setup is `.github/actions/os-server`. `ultravnc.ps1` refuses unless
`RUNNER_ENVIRONMENT=github-hosted`: the service it installs outlives both the
job and the checkout, and a self-hosted runner is someone's real machine.

`vnc_passwd_hex.py` stays here: it turns a password into the hex blob
`ultravnc.ini` wants and touches nothing.

Against a server that is already up, the tests are just:

```powershell
uv run python -m unittest discover -v -s tests/functional -t . -p 'test_os_servers.py'
```

## What the setup has to get right

Each of these cost a CI round to find, so they are worth keeping written
down:

* **The install path is fixed; don't search for it.** Chocolatey always
  installs to `C:\Program Files\uvnc bvba\UltraVNC`. A recursive scan of
  `C:\Program Files` for `winvnc.exe` takes over five minutes on the loaded
  runner image.

* **The Chocolatey feed is flaky.** It intermittently returns a response
  that isn't valid XML, which choco reports as "Unable to find package"
  while still exiting 0. `ultravnc.ps1` retries, and decides success by
  whether `winvnc.exe` exists rather than by the exit code.

* **A password is mandatory.** UltraVNC refuses every incoming connection
  until one is set, regardless of `AuthRequired` — the server replies
  "Until a password is set, incoming connections cannot be accepted". There
  is no no-auth shortcut, so the `passwd=` entry in `ultravnc.ini` has to be
  computed; `vnc_passwd_hex.py` does that and explains the format.

* **It has to run as a service.** `winvnc.exe -run` on a fresh install opens
  an interactive Settings dialog instead of serving. `-install` plus
  `Start-Service` is UltraVNC's unattended-deployment path and serves
  headlessly.

## Readiness

An open RFB port is not readiness -- the Docker servers need a
drawn-content marker on top of it, and macOS needs whole-connection
retries (see `../screen-sharing`). UltraVNC has been reliable once the
port opens, since the Windows desktop session exists before the server is
ever started, but CI still runs the shared gate
(`tests/functional/wait_for_servers.py os`) here so a slow start shows up
as a wait rather than as a timeout inside a test.

## What it proves

The Windows runner has a real rendered desktop, so captures come back with
genuine, non-black content: `test_os_servers.py` asserts screen content
here, unlike on macOS (see `../screen-sharing`).
