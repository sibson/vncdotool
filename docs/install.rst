Installation
=================

vncdotool is available on PyPI_, so in most cases you should be able to simply run::

    pip install vncdotool

vncdotool relies on a number of libraries, the two major ones are Pillow_, the Python Imaging Library and
Twisted_, an asynchronous networking library.
While vncdotool should work with any recent version of these libraries sometimes things break.
If you are having issues getting things to work you can try using a stable set of libraries
and if you aren't already using it, and you should be, use a virtualenv_.::

    pip install virtualenv
    virtualenv venv-vncdotool
    # XXX requirements.txt from vncdotool source tree
    pip install -r requirements.txt
    pip install -e .


Windows
---------
If you are not familiar with Python, the most reliable way to install vncdotool is to use binary packages.


    1. Download Python, current 64-bit Windows Version, from `Official Python`_ website https://www.python.org/downloads/
    2. Start the installation > On the first screen of the installer...

        - Check the box for "Add Python to PATH", 
        - Any other check boxes can be left checked or unchecked per their default
        - Click "Customize installation"
        - On the Optional Features install page, no changes are needed
        - On the Advanced Options page...
            - Make sure the boxes for "Install for all users" and "Add Python to environment variables" are checked
            - Uncheck "Precompile standard library" unless needed for other projects
            - Any other check boxes can be left checked or unchecked per their default
        - Click "Install" at the bottom
    3. Open an elevated Windows PowerShell console:
        - Type "PowerShell" (without quotes) in the search field of the Windows taskbar
        - Click "Run as administrator" in the right pane above the search field
        - Type or paste each of the following lines below, pressing Enter after each line and waiting for each line to process (change “Python39” to different version as applicable)::

            [Environment]::SetEnvironmentVariable("Path", "$env:Path;C:\Program Files\Python39\;C:\Program Files\Python39\Scripts\", "User")
            python -m pip install --upgrade pip
            pip install vncdotool

    4. At a Powershell prompt::

        vncdo.exe --server som.eip.add.res type "Hello World"

    5. If Hello World shows up on the remote machine that has a VNC server running then its time to celebrate.
       Otherwise, first check you can connect from your local machine to the remote using a normal GUI VNC Client.
       Once you get the normal GUI client working try vncdotool again and if you still have problems try the community at Stackoverflow_\ .

.. _PyPI: https://pypi.python.org/pypi
.. _Pillow: https://python-pillow.org/
.. _PIL Downloads: https://pypi.org/project/pillow/
.. _Official Python: https://python.org/downloads/
.. _Twisted: https://twistedmatrix.com/
.. _Twisted Downloads: https://pypi.org/project/Twisted/
.. _virtualenv: https://virtualenv.pypa.io/
.. _Stackoverflow: https://stackoverflow.com/questions/ask?tags=vncdotool
