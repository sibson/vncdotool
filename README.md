[![PyPi Package](https://img.shields.io/pypi/v/vncdotool)](https://pypi.org/project/vncdotool/)
[![Python Versions](https://img.shields.io/pypi/pyversions/vncdotool.svg)](https://pypi.python.org/pypi/vncdotool)
[![Actions Status](https://github.com/sibson/vncdotool/workflows/VNCDo%20CI/badge.svg)](https://github.com/sibson/vndotool/actions)
[![Coverage](https://codecov.io/gh/sibson/vncdotool/branch/main/graph/badge.svg)](https://app.codecov.io/gh/sibson/vncdotool)
[![ReadTheDocs](https://readthedocs.org/projects/vncdotool/badge/?version=latest&style=flat)](https://vncdotool.readthedocs.io/en/latest/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

# vncdotool

vncdotool is a command line VNC client.
It can be useful to automating interactions with virtual machines or
hardware devices that are otherwise difficult to control.

It's under active development and seems to be working, but please report any problems you have.

## Quick Start

To use vncdotool you need a VNC server.
Most virtualization products include one, or use RealVNC, TightVNC, or clone your Desktop using x11vnc.

Once, you have a server running you can install vncdotool from pypi:

```
pip install vncdotool
```

and then send a message to the vncserver with:

```
vncdo -s vncserver type "hello world"
```

The `vncserver` argument needs to be in the format `address[:display|::port]`. For example:

```
# connect to 192.168.1.1 on default port 5900
vncdo -s 192.168.1.1 type "hello world"

# connect to localhost on display :3 (port 5903)
vncdo -s localhost:3 type "hello world"

# connect to myvncserver.com on port 5902 (two colons needed)
vncdo -s myvncserver.com::5902 type "hello world"

# connect via IPv6 to localhost on display :3 (port 5903)
vncdo -s '[::1]:3' type "hello IPv6"
#         ^   ^ mind those square brackets around the IPv6 address
```

You can also take a screen capture with:

```
vncdo -s vncserver capture screen.png
```

More documentation can be found on [Read the Docs](http://vncdotool.readthedocs.org).

## Server Support

vncdotool speaks standard RFB and works with far more servers than we test.
This table says what we have evidence for, not what works.

| Server | Level | What CI exercises |
|---|---|---|
| [TigerVNC](https://tigervnc.org) | Verified | Everything: VNC password, VeNCrypt X509 and anonymous TLS, 5 encodings, 4 pixel formats |
| [x11vnc](https://github.com/LibVNC/x11vnc) | Verified | 6 encodings, the only one we see emit CoRRE; 4 pixel formats |
| [wayvnc](https://github.com/any1/wayvnc) | Verified | wlroots; Raw, ZRLE and Tight — all neatvnc has; VeNCrypt X509 |
| [LibVNCServer](https://libvnc.github.io) | Verified | Its `example` server: connect, input, capture. No X server, so no scenes |
| [KasmVNC](https://kasmweb.com/kasmvnc) | Verified | Native `ws://`; connect, input, capture |
| [QEMU](https://qemu.org) built-in | Verified | `ws://` and `wss://`; connect, input, capture. Firmware screen, so no scenes |
| [Selenoid](https://aerokube.com/selenoid/) | Verified | `ws://` with the session in the URL path |
| UltraVNC | Verified | Windows, CI runners only |
| Apple Screen Sharing | Verified | macOS, ARD authentication, CI runners only |
| Everything else | Unknown | RealVNC, TightVNC, TurboVNC, PiKVM, … |

**Verified** — every pull request connects, authenticates, sends a key and a
pointer event and captures a screen, plus every encoding and pixel format that
server implements. The third column says what that came to, because it is not
the same everywhere: a server that implements three encodings is verified for
three.

**Known-broken** — we tried it and it does not work. Nothing is at this level
today.

**Community** — reported working by a user, with the vncdotool and server
versions and the date it was tried. Not run by CI, so it ages.

**Unknown** — we have never tested it. It should work; we make no claim.
A report of success or failure is welcome, and is how a server reaches the
table.

`vncdo` also reaches servers through [websockify](https://github.com/novnc/websockify),
which is what noVNC deployments put in front of a VNC server —
`selenium/standalone-chrome`, the most-pulled VNC-bearing image on Docker Hub,
is x11vnc behind exactly that. KasmVNC, QEMU and Selenoid need no proxy; they
speak RFB over WebSocket themselves.

Testing LibVNCServer's `example` server covers more than the demo: LibVNCServer
is what gets embedded when a VNC server is bolted onto something that is not a
desktop. Proxmox VE's `vncterm` statically links it, and so do VirtualBox's
VBoxVNC, OpenBMC's `obmc-ikvm`, KDE's krfb, x11vnc and droidVNC-NG.

### What the tests prove

The suites answer different questions, and none of them subsumes another.

- **The smoke test** runs one server and answers one question: can we talk to a
  VNC server at all. It is the fast path, so a fleet that came up stale or
  unreachable fails in seconds rather than minutes.
- **The compatibility grids** run the real `vncdo` against live servers in
  Docker, so they prove negotiation works against the server version installed
  *today*. They need Docker and run on Linux only.
- **The scene tests** show a server a committed PNG and demand the capture come
  back pixel-identical. The image is an independent oracle: it is the file the
  server was shown, not something our decoder produced. Paired with a check
  that the server really sent the encoding we asked for — servers answer with
  Raw for anything they do not implement, and a scene renders correctly either
  way.
- **The goldens** replay committed wire bytes with no fleet, no network and no
  reactor, so they run on every OS and Python version we support and in a
  contributor's `make test`. They catch our decoder regressing; they cannot
  catch a server changing its encoder.

`tests/servers/docker-compose.yml` is the fleet, `specs/testing-framework.md`
and `specs/decoder-goldens.md` the design.

## Feedback

If you need help getting VNCDoTool working try the community at [Stackoverflow](https://stackoverflow.com/questions/ask?tags=vncdotool).

Patches, and ideas for improvements are welcome and appreciated, via [GitHub](http://github.com/sibson/vncdotool) issues.
If you are reporting a bug or issue please include the version of both vncdotool
and the VNC server you are using it with.

## Acknowledgements

Thanks to Chris Liechti, techtonik and Todd Whiteman for developing the RFB
and DES implementations used by vncdotool.
Also, to the [TigerVNC](http://sourceforge.net/apps/mediawiki/tigervnc/index.php?title=Main_Page) project for creating a community focus RFB specification document
