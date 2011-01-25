vncdotool
********************************
With vncdotool you can interact with VNC servers from the command line

Currently under developement and altogether not ready for general use. It
does threaten to be useful one day.

Quick Start
--------------------------------
If you have a VNC server running you can quickly try out
vncdotool by running::

    python vncdotool/command.py -h hostaddr -d displaynum click 2

Which for most window managers will open a context menu at the top left
corner of the screen.  If you have PIL installed then you can do screen
captures too::

    python vncdotool/command.py -h hostaddr -d displaynum capture screen.png

Usage
--------------------------------

Acknowledgements
--------------------------------
Thanks to chris, techtonik and Todd Whiteman for developing the RFB and
DES impementations used by vncdotool.
