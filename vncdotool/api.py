""" Helpers to allow vncdotool to be intergrated into other applications.

This feature is under developemental, you're help testing and
debugging is appreciated.
"""

import threading
try:
    import queue
except ImportError:
    import Queue as queue
import logging

from twisted.internet import reactor
from twisted.internet.defer import maybeDeferred
from twisted.python.log import PythonLoggingObserver
from twisted.python.failure import Failure

from . import command
from .client import VNCDoToolFactory

__all__ = ['connect']

log = logging.getLogger('vncdotool.api')

_THREAD = None


class VNCDoException(Exception):
    pass


def connect(server, password=None):
    """ Connect to a VNCServer and return a Client instance that is usable
    in the main thread of non-Twisted Python Applications, EXPERIMENTAL.

    >>> from vncdotool import api
    >>> client = api.connect('host')
    >>> client.keyPress('c')
    >>> api.shutdown()

    You may then call any regular VNCDoToolClient method on client from your
    application code.

    If you are using a GUI toolkit or other major async library please read
    http://twistedmatrix.com/documents/13.0.0/core/howto/choosing-reactor.html
    for a better method of intergrating vncdotool.
    """
    if not reactor.running:
        global _THREAD
        _THREAD = threading.Thread(target=reactor.run, name='Twisted',
                         kwargs={'installSignalHandlers': False})
        _THREAD.daemon = True
        _THREAD.start()

        observer = PythonLoggingObserver()
        observer.start()

    factory = VNCDoToolFactory()
    if password is not None:
        factory.password = password

    host, port = command.parse_host(server)
    client = ThreadedVNCClientProxy(factory)
    client.connect(host, port)

    return client


def shutdown():
    if not reactor.running:
        return

    reactor.callFromThread(reactor.stop)
    _THREAD.join()


class ThreadedVNCClientProxy(object):

    def __init__(self, factory):
        self.factory = factory
        self.queue = queue.Queue()

    def connect(self, host, port=5900):
        reactor.callWhenRunning(reactor.connectTCP, host, port, self.factory)

    def disconnect(self):
        def disconnector(protocol):
            protocol.transport.loseConnection()
        reactor.callFromThread(self.factory.deferred.addCallback, disconnector)

    def __getattr__(self, attr):
        method = getattr(self.factory.protocol, attr)

        def errback(reason, *args, **kwargs):
            self.queue.put(Failure(reason))

        def callback(protocol, *args, **kwargs):
            def result_callback(result):
                self.queue.put(result)
                return result
            d = maybeDeferred(method, protocol, *args, **kwargs)
            d.addBoth(result_callback)
            return d

        def proxy_call(*args, **kwargs):
            reactor.callFromThread(self.factory.deferred.addCallbacks,
                                   callback, errback, args, kwargs)
            result = self.queue.get(timeout=60 * 60)
            if isinstance(result, Failure):
                raise VNCDoException(result)

            return result

        return proxy_call


if __name__ == '__main__':
    import sys

    logging.basicConfig(level=logging.DEBUG)

    server = sys.argv[1]
    password = sys.argv[2]
    client1 = connect(server, password)
    client2 = connect(server, password)

    client1.captureScreen('screenshot.png')

    for key in 'username':
        client2.keyPress(key)

    for key in 'passw0rd':
        client1.keyPress(key)

    client1.disconnect()
    client2.disconnect()
    shutdown()
