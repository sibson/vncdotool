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

If you have the Python Imaging Library (Pillow_) installed you can also
make screen captures of the session::

    > vncdo capture screenshot.png

Per RFC 6143, the cursor pseudo-encoding exists so a client can draw the
pointer locally instead of waiting on the server, cutting perceived lag for
someone driving the session live. vncdo drives sessions with scripted
commands rather than a live display, so that responsiveness rarely matters
here. ``--localcursor`` is mostly only useful if a particular server does not
otherwise draw the pointer into the framebuffer and you want it present in a
capture; ``--nocursor`` does the opposite, forcing the pointer out of
captures::

    > vncdo --localcursor capture screenshot.png

With Pillow_ installed, you can wait for the screen to match a known image::

    > vncdo expect somescreen.png

Every pixel has to be within a bound of the target, a whole number from 0
(identical) to 255. Left out, the bound is whatever the pixel format cannot
express, so a 5-bit-red server does not poll forever waiting to reproduce an
8-bit value. To allow more, write it after the filename or pass
``--expect-fuzz``::

    > vncdo expect somescreen.png 16
    > vncdo --expect-fuzz 16 expect somescreen.png

``--jpeg-quality`` also blurs both images before comparing, because a JPEG
frame is further from its target than any bound can separate from a wrong
screen. ``--expect-blur RADIUS`` sets that radius, or ``0`` turns it off::

    > vncdo --encodings tight --jpeg-quality 5 --expect-fuzz 64 \
            expect somescreen.png

Before 2.0 the number after the filename was the root-mean-square difference
between the two images' histograms, a different measurement on a different
scale, so an old one cannot be converted and has to be picked again.
``expect somescreen.png 0`` still means exact and needs no change; a fuzz of
16 is a reasonable place to start for anything else.

Expect the new bound to be stricter than the old number suggests. A 2x2 patch
of the screen changing colour scores 126, where the old measurement scored
0.4 -- histograms record that colours moved, not where or how far.

Putting it all together you can specify multiple actions on a single
command line.  You could automate a login with the following::

    > vncdo type username key enter expect password_prompt.png
    > vncdo type password move 100 150 click 1 expect welcome_screen.png

Sometimes you only care about a portion of the screen, in which case you can
use rcapture and rexpect. For instance, if your login window appears at
x=100, y=200 and is 400 pixels wide by 250 high you could do::

    > vncdo rcapture region.png 100 200 400 250
    > vncdo rexpect region.png 100 200


Encodings
-------------------
By default vncdo asks the server for raw pixels: every server can send
them, and they cost the most bandwidth.  ``--encodings`` offers others, in
preference order, and the server sends whichever of them it has::

    > vncdo --encodings tight capture screen.png

The names are ``raw``, ``copyrect``, ``rre``, ``corre``, ``hextile``,
``zrle`` and ``tight``.  Tight sends less than raw on ordinary screen
content.  Three parts of tight are not implemented: the gradient filter,
TightPNG, and Tight Encoding Without Zlib.  A rectangle using any of them
ends the session with a message naming what arrived, exiting 20.  The tight
*security type*, which TightVNC servers want before they will authenticate
you, is not implemented either.

Some tight rectangles can be JPEG, which is lossy.  vncdo decodes them
whether or not it asked for them; a conforming server sends them only to a
client that asked for a JPEG quality level, and vncdo asks for none by
default, so a capture is exact unless you request otherwise.
``--jpeg-quality`` asks for one, on the RFB scale of 0 (low) to 9 (high)::

    > vncdo --encodings tight --jpeg-quality 8 capture screen.png


Exit Status
-------------------
vncdo exits 0 when every action completed.  Failures are grouped by cause, so
a script can tell a server that is down from one that rejected the password::

    > vncdo -s $HOST -p $PASSWORD type hello
    > case $? in
    >   0)  echo "done" ;;
    >   3)  echo "wrong password" ;;
    >   1?) echo "cannot reach $HOST" ;;
    >   *)  echo "failed" ;;
    > esac

===== ==================================================================
Code  Meaning
===== ==================================================================
0     all actions completed
1     unexpected error
2     bad command line or unknown action
3     authentication failed, usually a wrong password
10    could not connect: refused, unreachable, or name lookup failed
11    connection closed before the actions finished
20    server spoke something we could not understand
30    an action failed, such as writing a capture to an unwritable path
40    ``--timeout`` elapsed before the actions finished
===== ==================================================================

Single digits are for things you told us: the command line and the
credentials.  Failures out on the wire are grouped in tens by cause, so
new codes can be added to a group later.  Match on the group when you
only care about the category.


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
record a VNC session to a script which is playable by vncdo.  vnclog act as a
man-in-the-middle to record the VNC commands you issue with a client. So you
will have your vnclog connect to your server and your viewer connect to vnclog

    vncviewer ---> vnclog ---> vncserver

For best results be sure to set your vncviewer client to use the RAW encoding.
Others encoding may work but are not fully supported at this time.

The quickest way to get started is to run::

    > vnclog --viewer vncviewer keylog.vdo

For more control you can launch the viewer separately but be sure to connect
to the correct ports::

    > vnclog keylog.vdo
    > vncviewer localhost:2  # do something and then exit viewer
    > vncdo keylog.vdo

By running with --file-per-client vnclog will create a new file for every
client connection and record each clients activity.
This can be useful for quickly recording a number of testcases.::

    > vnclog --file-per-client --listen 6000 /tmp
    > vncviewer localhost::6000
    # do some stuff then exit and start new session
    > vncviewer localhost::6000
    # do some other stuff
    > ls /tmp/*.vdo

``vnclog`` keeps accepting connections until you stop it. Use ``--one-shot``
to record a single session and exit::

    > vnclog --one-shot --listen 6000 keylog.vdo

.. _Pillow: http://www.pythonware.com/products/pil
