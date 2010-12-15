vncdotool
::::::::::::::::
With vncdotool you can send keyboard and mouse events to a VNC server from 
the command line.

Currently under developement and altogether not ready for general use. One
day it might actually be useful.

Quick Start
--------------------------------
Assuming you have a VNC server already running you can quickly try out
vncdotool by running::

    python vncdotool -h hostaddr -d displaynum click 2

Which for most window managers will open a context menu at the top left
corner of the screen.

Usage
--------------------------------

Acknowledgements
--------------------------------
Thanks to 

(c) 2003 chris <cliechti@gmx.net>
(c) 2009 techtonik <techtonik@gmail.com>


whose python-vnc-viewer_, provided the RFB protocol implementation used by vncdotool.

_python-vnc_viewer: http://code.google.com/p/python-vnc-viewer/
