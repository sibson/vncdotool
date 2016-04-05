Embedding in Python Applications
===================================
vncdotool is built with the Twisted_ framework, as such it best intergrates with other Twisted Applications
Rewriting your application to use Twisted may not be an option, so vncdotool provides a compatability layer.
It uses a seperate thread to run the Twisted reactor and communitcates with the main program using a threadsafe Queue.

To use the syncronous API you can do the following::

    from vncdotool import api
    client = api.connect('vnchost:display')

You can then call any of the methods available on 
:class:`vncdotool.client.VNCDoToolClient` and they will block until completion.
For example::

    client.captureScreen('screenshot.png')
    client.keyPress('enter')
    client.expectScreen('login_success.png', maxrms=10)

This can be used to automate the starting of an Virtual Machine or other application::

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
