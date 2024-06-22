Embedding in Python Applications
===================================
vncdotool is built with the Twisted_ framework, as such it best integrates with other Twisted Applications.
Rewriting your application to use Twisted may not be an option, so vncdotool provides a compatibility layer.
It uses a separate thread to run the Twisted reactor and communicates with the main program using a thread-safe Queue.

..  warning::

    While the Twisted reactor runs as a *daemon* thread, the reactor itself will start additional *worker threads*, which are *no daemon threads*.
    Therefore the Reactor must be shut down explicitly by calling :func:`vncdotool.api.shutdown`.
    Otherwise your application will not terminate as those worker threads remain running in the background.

    This also applied when using the API as a context manager:
    As the reactor cannot be restarted, it is a design decision to not shut it down as the end of the context.
    That would prevent the API from being used multiple times in the same process.

To use the synchronous API you can do the following::

    from vncdotool import api
    client = api.connect('vncserver', password=None)

The first argument passed to the :func:`~vncdotool.api.connect` method is the VNC server to connect to, and it needs to be in the format ``address[:display|::port]``.
For example::

    # connect to 192.168.1.1 on default port 5900
    client = api.connect('192.168.1.1', password=None)

    # connect to localhost on display :3 (port 5903)
    client = api.connect('localhost:3', password=None)

    # connect to myvncserver.com on port 5902 (two colons needed)
    client = api.connect('myvncserver.com::5902', password=None)

You can then call any of the methods available on
:class:`vncdotool.client.VNCDoToolClient` and they will block until completion.
For example::

    client.captureScreen('screenshot.png')
    client.keyPress('enter')
    client.expectScreen('login_success.png', maxrms=10)

It is possible to set a per-client timeout in seconds to prevent calls from blocking indefinitely.

::

    client.timeout = 10
    try:
        client.captureScreen('screenshot.png')
    except TimeoutError:
        print('Timeout when capturing screen')

In case of too many timeout errors, it is recommended to reset the client connection via the `disconnect` and :func:`~vncdotool.api.connect` methods.

The :class:`vncdotool.client.VNCDoToolClient` supports the context manager protocol.

::

    with api.connect('vnchost:display') as client:
        client.captureScreen('screenshot.png')


The synchronous API can be used to automate the starting of a Virtual Machine or other application::

    vmtool.start('myvirtualmachine.img')
    client.connect('vmaddress::5950')
    client.expectScreen('booted.png')
    for k in 'username':
        client.keyPress(k)
    client.keyPress('enter')
    for k in 'password':
        client.keyPress(k)
    client.keyPress('enter')
    client.expectScreen('loggedin.png')
    client.disconnect()

    # continue with your testing session or other work

.. _Twisted: http://twistedmatrix.com/
