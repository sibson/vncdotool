# UltraVNC on Windows

An OS-hosted VNC server for vncdotool to test against on a Windows machine
(a GitHub `windows-latest` runner in CI). `setup.ps1` installs, configures
and starts it; `tests/functional/test_os_servers.py` then runs the same
connect/type/capture round trip used for the Docker servers, and
`collect-diagnostics.ps1` gathers the evidence when something goes wrong.

```powershell
pwsh tests/servers/ultravnc/setup.ps1
python -m unittest discover -v -s tests/functional -t . -p 'test_os_servers.py'
```

This turns the machine into an unattended remote-control target with a
password checked into version control, so only run it on a throwaway
machine.

## What the setup has to get right

Each of these cost a CI round to find, so they are worth keeping written
down:

* **The install path is fixed; don't search for it.** Chocolatey always
  installs to `C:\Program Files\uvnc bvba\UltraVNC`. A recursive scan of
  `C:\Program Files` for `winvnc.exe` takes over five minutes on the loaded
  runner image.

* **A password is mandatory.** UltraVNC refuses every incoming connection
  until one is set, regardless of `AuthRequired` — the server replies
  "Until a password is set, incoming connections cannot be accepted". There
  is no no-auth shortcut, so the `passwd=` entry in `ultravnc.ini` has to be
  computed; `vnc_passwd_hex.py` does that and explains the format.

* **It has to run as a service.** `winvnc.exe -run` on a fresh install opens
  an interactive Settings dialog instead of serving. `-install` plus
  `Start-Service` is UltraVNC's unattended-deployment path and serves
  headlessly.

## What it proves

The Windows runner has a real rendered desktop, so captures come back with
genuine, non-black content: `test_os_servers.py` asserts screen content
here, unlike on macOS (see `../screen-sharing`).
