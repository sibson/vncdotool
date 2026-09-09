# TigerVNC WinVNC on Windows

TigerVNC's Windows server, the third the OS-server job starts, on port 5902.
Named `tigervnc-win` to keep it apart from the containerised Xvnc the Docker
fleet calls `tigervnc`: same project, but a different screen grabber and a
real desktop behind it, which is the whole reason it is here. See
`specs/windows-cursor.md`.

## What the setup has to get right

* **Chocolatey's `tigervnc` package is the viewer, not the server.**
  TigerVNC split WinVNC out of the main Windows installer in 1.11, and the
  choco package tracks the viewer installer. The server is its own
  SourceForge download, `tigervnc64-winvnc-<version>.exe`, which `setup.ps1`
  fetches directly. `TIGERVNC_VERSION` overrides the version.

* **WinVNC is unmaintained upstream.** TigerVNC stopped supporting it in
  1.11 and its own release notes say so. That is a reason to read a failure
  here carefully rather than a reason to skip it: it is the closest
  free-to-install descendant of the RealVNC 4 codebase, which is what issue
  #206 was reported against and what nothing else in the matrix covers.

* **Configuration is in the registry.** `Password` is the same obfuscated
  8-byte blob the other two store, so `../vnc_passwd.py` computes it.

* **`-register` installs the service, not `-install`.**

* **`QueryConnect=0` matters.** With it on, an incoming connection raises a
  dialog on the server's desktop and the test waits for a click nobody will
  make.
