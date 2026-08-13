# Apple Screen Sharing on macOS

An OS-hosted VNC server for vncdotool to test against on a macOS machine (a
GitHub `macos-latest` runner in CI). `setup.sh` enables Remote Management
and creates the user vncdotool authenticates as;
`tests/functional/test_os_servers.py` then runs the same connect/type/capture
round trip used for the Docker servers, and `collect-diagnostics.sh` gathers
the evidence when something goes wrong.

```sh
sudo bash tests/servers/screen-sharing/setup.sh
python -m unittest discover -v -s tests/functional -t . -p 'test_os_servers.py'
```

This turns the machine into an unattended remote-control target with a
password checked into version control, so only run it on a throwaway
machine.

## What the setup has to get right

* **Authentication is ARD/Diffie-Hellman (security type 30), with a
  username.** vncdotool's existing ARD support handles the whole round trip;
  the server is reached as a local user created by `setup.sh`.

* **The legacy VNC password is dead.** `kickstart -setvnclegacy -vnclegacy
  yes -setvncpw` is accepted silently on current macOS, but the server still
  demands ARD auth afterwards. Don't reach for it as a way to avoid needing
  a username.

* **Screen Sharing is socket-activated on 5900.** Nothing has to be started
  beyond `kickstart -activate`; waiting for the port is enough.

## What it proves, and what it doesn't

Connect, RFB handshake, ARD authentication and key events all work. The
framebuffer, however, comes back fully black: a hosted runner has no
rendered desktop session behind it. So `vncservers.py` marks this server
`renders_desktop=False` and the test asserts the protocol round trip
without asserting pixels. Attaching a display to the runner, so pixel
assertions can be enabled here too, is a follow-up.
