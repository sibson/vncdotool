"""

(c) 2010 Marc Sibson

MIT License
"""

from rfb import RFBClient, RFBFactory
from twisted.internet import reactor
from twisted.internet.defer import Deferred


class VNCDoToolClient(RFBClient):
    x = 0
    y = 0

    def vncConnectionMade(self):
        self.setPixelFormat()
        self.factory.deferred.callback(self)

    def keyPress(self, key):
        self.keyEvent(ord(key), down=1)
        self.keyEvent(ord(key), down=0)
        return self

    def mousePress(self, button):
        buttons = 1 << button
        self.pointerEvent(self.x, self.y, buttonmask=buttons)
        self.pointerEvent(self.x, self.y, buttonmask=0)
        return self
        

    def mouseMove(self, x, y):
        self.x, self.y = x, y
        self.pointerEvent(x, y)
        return self

    def bell(self):
        print 'ding'

    def copy_text(self, text):
        print 'clip', repr(text)

    def paste(self, message):
        self.clientCutText(message)
        return self


class VNCDoToolFactory(RFBFactory):
    protocol = VNCDoToolClient
    password = None
    shared = 1

    def __init__(self):
        self.deferred = Deferred()

    def clientConnectionFailed(self, connector, reason):
        print 'connection failed', reason
        reactor.callLater(0, self.deferred.errback, reason)
        self.deferred = None
        

