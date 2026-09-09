# TightVNC on Windows

TightVNC 2.x, the second of three Windows servers the OS-server job starts,
on port 5901. It is here to separate UltraVNC's cursor behaviour from
Windows' — see `specs/windows-cursor.md` for what that means and what was
measured.

Against a server that is already up, the tests are just:

```powershell
uv run python -m unittest discover -v -s tests/functional -t . -p 'test_server_compat_native.py'
```

## What the setup has to get right

* **Chocolatey installs it but does not configure it.** The package
  registers and starts the `tvnserver` service with defaults — port 5900,
  no password — which collides with UltraVNC and refuses our connections.
  `setup.ps1` stops the service, writes the registry, and starts it again.

* **Configuration is in the registry, not a file.** The service runs as
  LocalSystem and reads HKLM; a value written to HKCU is silently ignored.

* **The password blob is the same one UltraVNC stores.** Both use the classic
  vncauth.c obfuscation, so `../vnc_passwd.py` computes it for both. TightVNC
  stores the eight bytes raw where UltraVNC's ini adds a ninth null.
