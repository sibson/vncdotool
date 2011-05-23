from twisted.protocols import portforward
from twisted.internet.protocol import Protocol
from vncdotool.client import VNCDoToolClient

from struct import unpack
import sys

TYPE_LEN = {
    0: 20,
    2: 4,
    3: 10,
    4: 8,
    5: 6,
}


class RFBServer(Protocol):

    def connectionMade(self):
        self.buffer = ''
        self.nbytes = 0
        # XXX send version message
        self._handler = self._handle_version

    def dataReceived(self, data):
        self.buffer += data
        while self.buffer and self.nbytes != len(self.buffer):
            self.nbytes = len(self.buffer)
            self._handler()

    def _handle_version(self):
        self.buffer = self.buffer[12:]
        self._handler = self._handle_security
        # XXX handle version request
        # XXX send security

    def _handle_security(self):
        sectype = self.buffer[0]
        # XXX do something with sectype
        # XXX send security data
        # XXX send security result
        self.buffer = self.buffer[1:]
        self._handler = self._handle_clientInit

    def _handle_clientInit(self):
        shared = self.buffer[0]
        self.buffer = self.buffer[1:]
        # XXX react to shared
        # XXX send serverInit
        self._handler = self._handle_protocol

    def _handle_protocol(self):
        ptype = unpack('!B', self.buffer[0])[0]
        nbytes = TYPE_LEN.get(ptype, 0)
        if len(self.buffer) < nbytes:
            return

        block = self.buffer[1:nbytes]
        self.buffer = self.buffer[nbytes:]
        if ptype == 0:
            args = unpack('!xxxBBBBHHHBBBxxx', block)
            self.handle_setPixelFormat(*args)
        elif ptype == 2:
            nencodings = unpack('!xH', block)[0]
            nbytes = 4 * nencodings
            encodings = unpack('!' + 'I' * nencodings, self.buffer[:nbytes])
            self.buffer = self.buffer[nbytes:]
            self.handle_setEncodings(encodings)
        elif ptype == 3:
            inc, x, y, w, h = unpack('!BHHHH', block)
            self.handle_framebufferUpdate(x, y, w, h, inc)
        elif ptype == 4:
            down, key = unpack('!BxxI', block)
            self.handle_keyEvent(key, down)
        elif ptype == 5:
            buttonmask, x, y = unpack('!BHH', block)
            self.handle_pointerEvent(x, y, buttonmask)
        elif ptype == 6:
            self.handle_clientCutText(block)

    def handle_setPixelFormat(self, bbp, depth, bigendian, truecolor, rmax, gmax, bmax, rshift, gshift, bshift):
        pass

    def handle_setEncodings(self, encodings):
        pass

    def handle_framebufferUpdate(self, x, y, w, h, incremental):
        pass

    def handle_keyEvent(self, key, down):
        pass

    def handle_pointerEvent(self, x, y, buttonmask):
        pass

    def handle_clientCutText(self, block):
        pass


class NullTransport(object):

    def write(self, data):
        return

    def writeSequence(self, data):
        return


class VNCLoggingClientProxy(portforward.ProxyClient):
    client = None
    ncaptures = 0

    def startLogging(self):
        self.client = VNCDoToolClient()
        self.client.transport = NullTransport()
        self.client.factory = self.peer.factory
        self.client.connectionMade()
        self.client._handler = self.client._handleExpected
        self.client.expect(self.client._handleVNCAuthResult, 4)

        d = self.client.updates.get()
        d.addCallback(self.saveScreen)

    def dataReceived(self, data):
        portforward.ProxyClient.dataReceived(self, data)
        if self.client:
            self.client.dataReceived(data)

    def saveScreen(self, image):
        self.ncaptures += 1
        filename = 'vncproxy%d.png' % self.ncaptures
        image.save(filename)
        self.peer.factory.logger('expect %s\n' % filename)
        d = self.client.updates.get()
        d.addCallback(self.saveScreen)


class VNCLoggingClientFactory(portforward.ProxyClientFactory):
    protocol = VNCLoggingClientProxy


class VNCLoggingServerProxy(portforward.ProxyServer, RFBServer):
    clientProtocolFactory = VNCLoggingClientFactory
    server = None
    buttons = 0

    def connectionMade(self):
        portforward.ProxyServer.connectionMade(self)
        RFBServer.connectionMade(self)
        self.mouse = (None, None)

    def dataReceived(self, data):
        RFBServer.dataReceived(self, data)
        portforward.ProxyServer.dataReceived(self, data)

    def _handle_security(self):
        RFBServer._handle_security(self)
        self.peer.startLogging()

    def handle_keyEvent(self, key, down):
        if down:
            self.factory.logger('key %c\n' % key)

    def handle_pointerEvent(self, x, y, buttonmask):
        if self.mouse != (x, y):
            self.factory.logger('move %d %d\n' % (x, y))
            self.mouse = x, y

        for button in range(1, 9):
            if buttonmask & (1 << (button - 1)):
                self.factory.logger('click %d\n' % button)


class VNCLoggingServerFactory(portforward.ProxyFactory):
    protocol = VNCLoggingServerProxy
    logger = sys.stdout.write
    shared = True
    password = None

    def clientConnectionMade(self, client):
        self.client = client
