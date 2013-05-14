""" Helpers to allow vncdotool to be intergrated into other applications.

This is developemental feature and should only be used if you are willing
to debug possible issues.
"""

import threading
from Queue import Queue

from twisted.internet import reactor

from vncdotool import command
from vncdotool.client import VNCDoToolFactory


class ThreadedVNCClient(object):
    def __init__(self, factory):
        self.factory = factory

    def _connected(self, client):
        self.client = client
        print 'connected', client

    def __getattr__(self, attr):
        return self._wrap(getattr(self.client, attr))

    def _wrap(self, method):
        

def connect(server):
    """
    """

    factory = VNCDoToolFactory()
    client = ThreadedVNCClient(factory)
    factory.deferred.addCallback(client._connected)

    host, port = command.parse_host(server)
    reactor.connectTCP(host, port, factory)

    t = threading.Thread(target=reactor.run)
    t.run()

    return client


if __name__ == '__main__':
    import time

    client = connect('localhost')

    client.type
    time.sleep(10)
