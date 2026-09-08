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
This says what we have evidence for, not what works.

**Supported** — all basic function known to work, regression tested on every
pull request: [TigerVNC](https://tigervnc.org),
[x11vnc](https://github.com/LibVNC/x11vnc),
[wayvnc](https://github.com/any1/wayvnc),
[LibVNCServer](https://libvnc.github.io),
[KasmVNC](https://kasmweb.com/kasmvnc), [QEMU](https://qemu.org)'s built-in
server, [Selenoid](https://aerokube.com/selenoid/), UltraVNC on Windows and
Apple Screen Sharing on macOS.

**Compatible** — a user reported it working, or we ran the compatibility suite
against it once. Not tracked by CI, so it ages. Nothing listed yet.

**Broken** — we tried it and it does not work. Nothing listed yet.

**TBD** — no data gathered: RealVNC, TightVNC, TurboVNC, PiKVM, and everything
else. It should work; we make no claim. A report either way is welcome, and is
how a server moves up.

`vncdo` also reaches servers through [websockify](https://github.com/novnc/websockify),
which is what noVNC deployments put in front of a VNC server —
`selenium/standalone-chrome`, the most-pulled VNC-bearing image on Docker Hub,
is x11vnc behind exactly that. KasmVNC, QEMU and Selenoid need no proxy; they
speak RFB over WebSocket themselves.

### What the tests prove

The suites answer different questions, and none of them subsumes another.

- **The smoke test** is the critical user journey: connect, send input, capture
  a screen. It catches `vncdo` breaking outright.
- **The compatibility grids** drive real products, so they cover a wider variety
  of settings and behaviours than a fixture can carry.
- **The scene tests** are decoder resilience to variation in server behaviour,
  held against the image the server was actually shown rather than against
  anything our decoder produced.
- **The goldens** replay committed wire bytes offline, so any feature can be
  tested on every OS we support — and a server nobody can deploy locally or in
  CI can still be covered, by someone sending us a capture of it.

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
