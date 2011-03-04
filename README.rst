vncdotool
********************************
With vncdotool you can interact with VNC servers from the command line

Currently under developement, so use at your own peril but what is the
worst that could happen?

Quick Start
--------------------------------
If you have a VNC server running you can quickly try out
vncdotool by running::

    python vncdotool/command.py -h hostaddr -d displaynum click 2

Which for most window managers will open a context menu at the top left
corner of the screen.  If you have PIL installed then you can do screen
captures too::

    python vncdotool/command.py -h hostaddr -d displaynum capture screen.png

Install
--------------------------------
You will need to have Twisted installed, http://twistedmatrix.com.
Optionally, you will also need the Python Imaging Library,
http://www.pythonware.com/products/pil/.  Once you have the
dependencies installed you can install vncdotool from source with::

    python setup.py install

Usage
--------------------------------
Once installed you can use the vncdotool command to send keys, for
alphanumeric you just specify the character.  For other keys names are
used::

    vncdotool key a
    vncdotool key 5
    vncdotool key .
    vncdotool key enter
    vncdotool key shift-a
    vncdotool key ctrl-C
    vncdotool key ctrl-alt-del

To enter data you can use the type command, which only supports
alphanumeric::

    vncdotool type hello

You can also control the mouse pointer with move and click::

    vncdotool move 100 100
    vncdotool click 1

If you have the Python Imaging Library (PIL) installed you can also
make screen captures of the session::

    vncdotool capture screenshot.png

Again if you have PIL, you can wait for the screen to match a
known image.  This is useful for waiting for the server to be in a
known state::

    vncdotool expect somescreen.png 0

Finally, you may specify multiple actions on a single command line::

    vncdotool type username key enter expect password_prompt.png
    vncdotool type password move 100 150 click 1 expect welcome_screen.png

Feedback
--------------------------------
Comments, suggestions and patches are welcome and appreciated.  They can
be sent to sibson+vncdotool@gmail.com or via
http://github.com/sibson/vncdotool.

Acknowledgements
--------------------------------
Thanks to chris, techtonik and Todd Whiteman for developing the RFB and
DES impementations used by vncdotool.
