# vncdotool

vncdotool is a command line VNC client.
It can be useful to automating interactions with virtual machines or
hardware devices that are otherwise difficult to control.

It's under active development and seems to be working, but please report any problems you have.

## Quick Start

To use vncdotool you will need a VNC server.
Most virtualization products include one, or use RealVNC, TightVNC or clone your Desktop using x11vnc.

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

See [Installation](install.md) and [Usage](usage.md) for the rest.

## Feedback

If you need help getting VNCDoTool working try the community at [Stackoverflow](https://stackoverflow.com/questions/ask?tags=vncdotool).

Patches, and ideas for improvements are welcome and appreciated, via [GitHub](https://github.com/sibson/vncdotool) issues.
If you are reporting a bug or issue please include the version of both vncdotool
and the VNC server you are using it with.

## Acknowledgements

Thanks to Chris Liechti, techtonik and Todd Whiteman for developing the RFB
and DES implementations used by vncdotool.
Also, to the [TigerVNC](http://sourceforge.net/apps/mediawiki/tigervnc/index.php?title=Main_Page) project for creating a community focus RFB specification document
