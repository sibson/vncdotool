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

| Server | Level | Notes |
|---|---|---|
| [TigerVNC](https://tigervnc.org) | Verified | VNC password and VeNCrypt, X509 and anonymous TLS |
| [x11vnc](https://github.com/LibVNC/x11vnc) | Verified | The only server we see emit CoRRE |
| [wayvnc](https://github.com/any1/wayvnc) | Verified | wlroots; Raw, ZRLE and Tight, VeNCrypt X509 |
| [LibVNCServer](https://libvnc.github.io) | Smoke | Its `example` server |
| [KasmVNC](https://kasmweb.com/kasmvnc) | Smoke | `ws://` only |
| [QEMU](https://qemu.org) built-in | Smoke | `ws://` and `wss://` |
| [websockify](https://github.com/novnc/websockify) / noVNC | Smoke | `ws://` and `wss://` |
| [Selenoid](https://aerokube.com/selenoid/) | Smoke | `ws://`, session in the URL path |
| UltraVNC | Smoke | Windows, CI only |
| Apple Screen Sharing | Smoke | macOS, ARD authentication, CI only |
| Everything else | Unknown | RealVNC, TightVNC, TurboVNC, Vino, … |

**Verified** — every pull request runs the full compatibility grid against it:
connect, authenticate, keypress, pointer, and a pixel-exact screen capture at
every encoding and pixel format that server implements.

**Smoke** — every pull request connects, authenticates, sends a key and a
pointer event, and captures a screen. Encodings and pixel formats are not
exercised.

**Unknown** — we have never tested it. It should work; we make no claim.
A report of success or failure is welcome, and is how a server reaches the
table.

**Community** — reported working by a user, with the vncdotool and server
versions and the date it was tried. Not run by CI, so it ages.

### What the tests prove

The suites answer different questions, and none of them subsumes another.

- **The compatibility grid** runs the real `vncdo` against live servers in
  Docker, so it proves negotiation works against the server version installed
  *today*. It needs Docker and runs on Linux only.
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
