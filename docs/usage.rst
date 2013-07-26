Usage
==============


Basic Usage
-------------
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


Running Scripts
-------------------
For more complex automation you can read commands from stdin or a file.
The file format is simply a collection of actions::

    > echo "type hello" | vncdo -

Or if you had a file called login.vdo with the following content::

    # select the name text box, enter your name and submit
    move 100 100 click 1 type "my name" key tab key enter

    # grab the result
    capture screenshot.png

You could run it with the following command::

    > vncdo login.vdo


Creating Scripts
------------------
While you can create scripts by hand it can often be a time consuming process.
To make the process easier vncdotool provides a log mode that allows a user to 
record a VNC session to a script which is playable by vncdo.

For best results be sure to set your vncviewer client to use the RAW encoding.
Others encoding may work but are not fully supported at this time.::

    > vnclog keylog.vdo
    > vncviewer localhost:2  # do something and then exit viewer
    > vncdo keylog.vdo

If its too hard to remember which port to use you can tell vncdotool to
launch a viewer that will already be connected to the vnclog session.::

    > vnclog --viewer vncviewer keylog.vdo

By running with --forever vncdotool will create a new file for every client 
connection and record each clients activity.
This can be useful for quickly recording a number of testcases.::

    > vnclog --forever --listen 6000 /tmp
    > vncviewer localhost::6000  
    # do some stuff then exit and start new session
    > vncviewer localhost::6000
    # do some other stuff
    > ls /tmp/*.vdo

Sometimes you only care about a portion of the screen, in which case you can
use rcapture and rexpect.
For instance, if your login window appears at x=100, y=200) and is 400 pixels wide by 250 high you could do::

    > vncdo rcapture region.png 100 200 400 250
    > vncdo rexpect region.png 100 200 0


.. _PIL: http://www.pythonware.com/products/pil
