.. image:: https://img.shields.io/pypi/v/vncdotool.svg :target: https://pypi.python.org/pypi/vncdotool
.. image:: https://img.shields.io/travis/sibson/vncdotool.svg :target: https://travis-ci.org/sibson/vncdotool

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

    vncdo -s vncserveraddress type "hello world"

You can also take a screen capture with::

    vncdo -s vncservername capture screen.png


More documentation can be found on `Read the Docs`_.

Feedback
--------------------------------
Comments, suggestions and patches are welcome and appreciated.
They can be sent to via GitHub_, vncdotool@googlegroups.com or sibson+vncdotool@gmail.com.

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
