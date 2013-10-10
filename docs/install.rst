Installation
=================

vncdotool is available on PyPI_, so in most cases you should be able to simply run::

    pip install vncdotool

vncdotool relies on a number of libraries, the two major ones are PIL_, the Python Imaging Library and
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
Currently, (Oct 2013) PIL only provides 32bit binary packages for Windows, so you will need to install a 32bit python.

    1. Download and install python-2.7.5.exe from the `Python Downloads`_ website
    2. Open up Powershell, and paste in the following::

        [Environment]::SetEnvironmentVariable("Path", "$env:Path;C:\Python27\;C:\Python27\Scripts\", "User")

    3. Restart your Windows Machine
    4. Upon Restart, go to the `Twisted Downloads`_ and get and install 32bit Twisted, Twisted-13.1.0.win32-py2.7.exe
    5. Download and install PIL-1.1.7.win32-py2.7.exe, from `PIL Downloads`_.
    6. Download ez_setup.py and get_pip.py and save them to your `Python/Scripts` folder, ``C:\Python27\Scripts``
    7. Open up Powershell and type the following::

        pip install pip --upgrade
        pip install distribute
        pip install setuptools --upgrade
        pip install Twisted --upgrade
        pip install vncdotool < -- Finally install vncdotool

    8. At a Powershell prompt::

        vncdo.exe --server som.eip.add.res type "Hello World"

    9. If Hello World shows up on the remote machine that has a VNC server running then its time to celebrate.
       Otherwise, first check you can connect from your local machine to the remote using a normal GUI VNC Client.
       Once you get the normal GUI client working try vncdotool again and if you still have problems contact sibson+vncdotool@gmail.com.

.. _PyPI: https://pypi.python.org/pypi
.. _PIL: http://www.pythonware.com/products/pil/
.. _PIL Downloads: http://www.pythonware.com/products/pil/
.. _Python Downloads: http://python.org/download/
.. _Twisted: http://twistedmatrix.com/
.. _Twisted Downloads: http://twistedmatrix.com/trac/wiki/Downloads
.. _virtualenv: http://www.virtualenv.org/
.. _ez_setup.py: https://bitbucket.org/pypa/setuptools/raw/bootstrap/ez_setup.py
.. _get_pip.py: https://raw.github.com/pypa/pip/master/contrib/get-pip.py
