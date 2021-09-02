.. image:: https://img.shields.io/pypi/v/vncdotool   :alt: PyPI

vncdotool
===========
vncdotool is a command line VNC client.
It can be useful to automating interactions with virtual machines or
hardware devices that are otherwise difficult to control.

It's under active development and seems to be working, but please report any problems you have.

Quick Start
--------------------------------
To use vncdotool you will need a VNC server.
Most virtualization products include one, or use RealVNC, TightVNC or clone your Desktop using x11vnc.

Once, you have a server running you can install vncdotool from pypi::

    pip install vncdotool

and then send a message to the vncserver with::

    vncdo -s vncserver type "hello world"

The `vncserver` argument needs to be in the format `address[:display|::port]`. For example::

    # connect to 192.168.1.1 on default port 5900
    vncdo -s 192.168.1.1 type "hello world"

    # connect to localhost on display :3 (port 5903)
    vncdo -s localhost:3 type "hello world"

    # connect to myvncserver.com on port 5902 (two colons needed)
    vncdo -s myvncserver.com::5902 type "hello world"

You can also take a screen capture with::

    vncdo -s vncserver capture screen.png


More documentation can be found on `Read the Docs`_.

Feedback
--------------------------------
If you need help getting VNCDoTool working try the communinity at `_Stackoverflow`

Patches, and ideas for improvements are welcome and appreciated, via `_GitHub` issues.
If you are reporting a bug or issue please include the version of both vncdotool
and the VNC server you are using it with.


Acknowledgements
--------------------------------
Thanks to Chris Liechti, techtonik and Todd Whiteman for developing the RFB
and DES implementations used by vncdotool.
Also, to the TigerVNC_ project for creating a community focus RFB specification document



.. _Read The Docs: http://vncdotool.readthedocs.org
.. _GitHub: http://github.com/sibson/vncdotool
.. _TigerVNC: http://sourceforge.net/apps/mediawiki/tigervnc/index.php?title=Main_Page
.. _python-vnc-viewer: http://code.google.com/p/python-vnc-viewer
.. _Stackoverflow: https://stackoverflow.com/questions/ask?tags=vncdotool
