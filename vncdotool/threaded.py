""" Helpers to allow vncdotool to be intergrated into other applications.

This is developemental feature and should only be used if you are willing
to debug possible issues.
"""

import threading
import logging

from twisted.internet import reactor

from vncdotool import command
from vncdotool.client import VNCDoToolFactory, VNCDoToolClient

log = logging.getLogger('vncdo.thread')


def connect(server):
    """ Connect to a VNCServer and return a Client instance that is usable
    in the main thread of non-Twisted Python Applications, EXPERIMENTAL.

    >>> client = threaded.connect('host')
    >>> client.keyPress('c')
    >>> client.join()

    If you are using a GUI toolkit or other major async library please read
    http://twistedmatrix.com/documents/13.0.0/core/howto/choosing-reactor.html
    for a better method of intergrating vncdotool.
    """
    factory = VNCDoToolFactory()
    client = ThreadedVNCClient(factory)
    factory.deferred.addCallback(client._connected)

    host, port = command.parse_host(server)
    client.connect(host, port)
    client.start()

    return client


class ThreadedVNCClient(object):

    def __init__(self, factory):
        self.factory = factory
        self.client = None

    def connect(self, host, port=5900):
        reactor.callWhenRunning(reactor.connectTCP, host, port, self.factory)

    def start(self):
        self.thread = threading.Thread(target=reactor.run, name='Twisted',
                                       kwargs={'installSignalHandlers': False})
        self.thread.daemon = True
        self.thread.start()

        return self.thread

    def join(self):
        log.debug('waiting for thread to finish')
        reactor.callFromThread(self.factory.deferred.addCallback, self._stop)
        self.thread.join()

    def _connected(self, client):
        self.client = client
        log.debug('connected %s', client)
        return client

    def __getattr__(self, attr):
        method = getattr(VNCDoToolClient, attr)

        def wrapped(*args, **kwargs):
            log.debug('adding Callback %s %s %s', method, args, kwargs)
            reactor.callFromThread(self.factory.deferred.addCallback, method,
                                   *args, **kwargs)
        return wrapped

    def _stop(self, client):
        reactor.stop()




if __name__ == '__main__':
    logging.basicConfig()
    logging.getLogger().setLevel(logging.DEBUG)

    server = 'vncdobox.local'
    client = connect(server)

    r = client.keyPress('t')
    client.join()
