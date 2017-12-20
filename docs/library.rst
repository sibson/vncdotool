Embedding in Python Applications
===================================
vncdotool is built with the Twisted_ framework, as such it best intergrates with other Twisted Applications
Rewriting your application to use Twisted may not be an option, so vncdotool provides a compatability layer.
It uses a seperate thread to run the Twisted reactor and communitcates with the main program using a threadsafe Queue.

To use the syncronous API you can do the following::

    from vncdotool import api
    client = api.connect('vnchost:display', password=None)

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
    except VNCDoException:
        print('Timeout when capturing screen')

In case of too many timeout errors, it is recommended to reset the client connection via the `disconnect` and `connect` methods.

The syncronous API can be used to automate the starting of a Virtual Machine or other application::

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
