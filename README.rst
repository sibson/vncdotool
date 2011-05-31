vncdotool
********************************
vncdotool is a command line VNC client.

It comes in handy when automating interactions with virtual machines or
some hardware devices that are otherwise difficult to control.

Currently under development, so use at your own peril but what is the
worst that could happen?

Quick Start
--------------------------------
To see vncdotool in action you can run it against an existing VNC server
or start one locally with x11vnc. Then you can run::

    pip install twisted # if you don't already have it
    python vncdotool/command.py -s hostaddr type "hello world"

If you have PIL installed then you can do a screen captures with::

    python vncdotool/command.py -s hostaddr capture screen.png

Installation
--------------------------------
vncdotool depends on Twisted. Additionally, for capture and expect commands
to work you will need the Python Image Library. You can use your
favourite package manager to grab them.  Once you have the dependencies
installed you install from the unpacked source tree.

    python setup.py install

Usage
--------------------------------
Once installed you can use the vncdotool command to send key-presses.
Alphanumerics are straightforward just specify the character.  For other
keys longer names are used::

    vncdotool key a
    vncdotool key 5
    vncdotool key .
    vncdotool key enter
    vncdotool key shift-a
    vncdotool key ctrl-C
    vncdotool key ctrl-alt-del

To type longer strings when entering data or commands you can use the type c
command, which does not support special characters::

    vncdotool type "hello world"

You can control the mouse pointer with move and click commands::

    vncdotool move 100 100
    vncdotool click 1

If you have the Python Imaging Library (PIL) installed you can also
make screen captures of the session::

    vncdotool capture screenshot.png

With PIL, you can wait for the screen to match a known image.::

    vncdotool expect somescreen.png 0

Putting it all together you can specify multiple actions on a single
command line.  You could automate a login with the following::

    vncdotool type username key enter expect password_prompt.png
    vncdotool type password move 100 150 click 1 expect welcome_screen.png

Creating long lists of commands can be time consuming so vncdotool provides
a proxy mode that logs messages and screen captures.  The log can then be
edited and played back.::

    vncdotool proxy 6000 > vnc.log
    vncviewer localhost:6000
    sed -i s/click 1/click 2/ vnc.log
    vncdotool < vnc.log

Feedback
--------------------------------
Comments, suggestions and patches are welcome and appreciated.  They can
be sent to sibson+vncdotool@gmail.com or via
http://github.com/sibson/vncdotool.

Acknowledgements
--------------------------------
Thanks to Chris Liechti, techtonik and Todd Whiteman for developing the RFB
and DES implementations used by vncdotool.

_python-vnc-viewer: http://code.google.com/p/python-vnc-viewer
_Twisted: http://twistedmatrix.com
_PIL: http://www.pythonware.com/products/pil
