vncdotool
=================
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

If you have PIL_ installed then you can do a screen captures with::

    python vncdotool/command.py -s hostaddr capture screen.png

Installation
--------------------------------
vncdotool depends on Twisted_. Additionally, for capture and expect commands
to work you will need the Python Image Library. You can use your
favourite package manager to grab them.  Once you have the dependencies
installed you install from the unpacked source tree.

    python setup.py install

Usage
--------------------------------
Once installed you can use the vncdotool command to send key-presses.
Alphanumerics are straightforward just specify the character.  For other
keys longer names are used::

    > vncdo key a
    > vncdo key 5
    > vncdo key .
    > vncdo key enter
    > vncdo key shift-a
    > vncdo key ctrl-C
    > vncdo key ctrl-alt-del

To type longer strings when entering data or commands you can use the type c
command, which does not support special characters::

    > vncdo type "hello world"

You can control the mouse pointer with move and click commands.
NOTE, you should almost always issue a move before a click, as in::

    > vncdo move 100 100 click 1

The following would seem to be equivalent but would actually click at (0, 0).
This occurs due to how click events are encoded by VNC, meaning you need to initialise the position of the mouse.::

    > vncdo move 100 100
    > vncdo click 1

If you have the Python Imaging Library (PIL_) installed you can also
make screen captures of the session::

    > vncdo capture screenshot.png

With PIL_ installed, you can wait for the screen to match a known image.::

    > vncdo expect somescreen.png 0

Putting it all together you can specify multiple actions on a single
command line.  You could automate a login with the following::

    > vncdo type username key enter expect password_prompt.png
    > vncdo type password move 100 150 click 1 expect welcome_screen.png

For more complex automation you can read commands from stdin or a file.
The file format is simply a collection of actions::

    > echo "type hello" | vncdo -

    > cat login.vdo
    # select the name text box, enter your name and submit
    move 100 100 click 1 type "my name" key tab key enter

    # grab the result
    capture screenshot.png

    > vncdo login.vdo

Creating long lists of commands can be time consuming so vncdotool provides
a log mode that records a users interactions to a file, which you can then
playback with vncdo.
For best results set your client to use the RAW encoding.
Others encoding may work but are not fully supported at this time.::

    > vnclog keylog.vdo
    > vncviewer localhost:2  # do something and then exit viewer
    > vncdo keylog.vdo

If its too hard to remember which port to use you can tell vncdotool to 
launch a client that will be connected to the vnclog session.::

    > vnclog --viewer vncviewer keylog.vdo

By running with --forever vncdotool will create a new file for every client 
connection and record each clients activity.
This can be useful for quickly recording a number of testcases.::

    > vnclog --forever --listen 6000 /tmp
    > vncviewer localhost::6000  # then exit and start new session
    > vncviewer localhost::6000
    > ls /tmp/*.vdo

Feedback
--------------------------------
Comments, suggestions and patches are welcome and appreciated.
They can be sent to sibson+vncdotool@gmail.com or via github_.
If you are reporting a bug or issue please include the version of both vncdotool
and the VNC server you are using it with.

Acknowledgements
--------------------------------
Thanks to Chris Liechti, techtonik and Todd Whiteman for developing the RFB
and DES implementations used by vncdotool.

.. _python-vnc-viewer: http://code.google.com/p/python-vnc-viewer
.. _Twisted: http://twistedmatrix.com
.. _PIL: http://www.pythonware.com/products/pil
.. _github: http://github.com/sibson/vncdotool.
