""" Helpers to allow vncdotool to be intergrated into other applications.

This feature is under developemental, you're help testing and
debugging is appreciated.
"""

import threading
import Queue
import logging

from twisted.internet import reactor
from twisted.internet.defer import maybeDeferred
from twisted.python.log import PythonLoggingObserver
from twisted.python.failure import Failure

from vncdotool import command
from vncdotool.client import VNCDoToolFactory, VNCDoToolClient

__all__ = ['connect']

log = logging.getLogger('vncdotool.api')


class VNCDoThreadError(Exception):
    pass


def connect(server, password=None):
    """ Connect to a VNCServer and return a Client instance that is usable
    in the main thread of non-Twisted Python Applications, EXPERIMENTAL.

    >>> from vncdotool import threaded
    >>> client = threaded.connect('host')
    >>> client.keyPress('c')
    >>> client.join()

    You may then call any regular VNCDoToolClient method on client from your
    application code.

    If you are using a GUI toolkit or other major async library please read
    http://twistedmatrix.com/documents/13.0.0/core/howto/choosing-reactor.html
    for a better method of intergrating vncdotool.
    """
    observer = PythonLoggingObserver()
    observer.start()

    factory = VNCDoToolFactory()
    if password is not None:
        factory.password = password
    client = ThreadedVNCClientProxy(factory)

    host, port = command.parse_host(server)
    client.connect(host, port)
    client.start()

    return client


class ThreadedVNCClientProxy(object):

    def __init__(self, factory):
        self.factory = factory
        self.queue = Queue.Queue()

    def connect(self, host, port=5900):
        reactor.callWhenRunning(reactor.connectTCP, host, port, self.factory)

    def start(self):
        self.thread = threading.Thread(target=reactor.run, name='Twisted',
                                       kwargs={'installSignalHandlers': False})
        self.thread.daemon = True
        self.thread.start()

        return self.thread

    def join(self):
        def _stop(result):
            reactor.stop()

        reactor.callFromThread(self.factory.deferred.addBoth, _stop)
        self.thread.join()

    def __getattr__(self, attr):
        method = getattr(VNCDoToolClient, attr)

        def _releaser(result):
            self.queue.put(result)
            return result

        def _callback(protocol, *args, **kwargs):
            d = maybeDeferred(method, protocol, *args, **kwargs)
            d.addBoth(_releaser)
            return d

        def proxy_call(*args, **kwargs):
            reactor.callFromThread(self.factory.deferred.addCallback,
                                   _callback, *args, **kwargs)
            result = self.queue.get()
            if isinstance(result, Failure):
                raise VNCDoThreadError(result)

        return proxy_call


if __name__ == '__main__':
    import sys

    logging.basicConfig()
    logging.getLogger().setLevel(logging.DEBUG)

    server = sys.argv[1]
    client = connect(server)

    # make a screen capture
    client.captureScreen('screenshot.png')

    # type a password
    for key in 'passw0rd':
        client.keyPress(key)

    client.join()
