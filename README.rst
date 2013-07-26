vncdotool
------------

vncdotool is a command line VNC client.
It can be useful to automating interactions with virtual machines or
hardware devices that are otherwise difficult to control.

It's under active development and seems to be working, but please report any problems you have.

Quick Start
--------------------------------
To use vncdotool you will need a VNC server, most virtualization products
include one, you can use RealVNC, TightVNC or clone you Desktop using x11vnc.

Once you have a server running you can install vncdotool from pypi::

    pip install vncdotool

and then send a message to the vncserver with::

    vncdo -s vncserveraddress type "hello world"

You can also take a screen capture with::

    vncdo -s vncservername capture screen.png


More documentation can be found at ReadtheDocs_.

Feedback
--------------------------------
Comments, suggestions and patches are welcome and appreciated.
They can be sent to sibson+vncdotool@gmail.com or via GitHub_.
If you are reporting a bug or issue please include the version of both vncdotool
and the VNC server you are using it with.

Acknowledgements
--------------------------------
Thanks to Chris Liechti, techtonik and Todd Whiteman for developing the RFB
and DES implementations used by vncdotool.
Also, to the TigerVNC_ project for creating a community focus RFB specification document



.. _ReadTheDocs: http://vncdotool.readthedocs.org
.. _GitHub: http://github.com/sibson/vncdotool
.. _TigerVNC: http://sourceforge.net/apps/mediawiki/tigervnc/index.php?title=Main_Page
.. _python-vnc-viewer: http://code.google.com/p/python-vnc-viewer
