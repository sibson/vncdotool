from struct import unpack
import sys
import time
import os.path
import logging


from twisted.protocols import portforward
from twisted.internet.protocol import Protocol

from .client import VNCDoToolClient, KEYMAP


log = logging.getLogger('proxy')

TYPE_LEN = {
    0: 20,
    2: 4,
    3: 10,
    4: 8,
    5: 6,
}

REVERSE_MAP = dict((v, n) for (n, v) in KEYMAP.items())


class RFBServer(Protocol):
    _handler = None

    def connectionMade(self):
        Protocol.connectionMade(self)
        self.transport.setTcpNoDelay(True)

        self.buffer = ''
        self.nbytes = 0
        # XXX send version message
        self._handler = self._handle_version, 12

    def dataReceived(self, data):
        self.buffer += data
        while len(self.buffer) >= self._handler[1]:
            self._handler[0]()

    def _handle_version(self):
        msg = self.buffer[:12]
        self.buffer = self.buffer[12:]
        if not msg.startswith('RFB 003.') and msg.endswith('\n'):
            self.transport.loseConnection()

        version = msg[8:11]
        if version in ('003', '005'):
            if self.factory.password_required:
                self._handler = self._handle_VNCAuthResponse, 16
            else:
                self._handler = self._handle_clientInit, 1
        elif version in ('007', '008'):
            # XXX send security v3.7+
            self._handler = self._handle_security, 1

    def _handle_security(self):
        sectype = self.buffer[0]
        self.buffer = self.buffer[1:]

    def _handle_VNCAuthResponse(self):
        self.buffer = self.buffer[16:]
        self._handler = self._handle_clientInit, 1

    def _handle_clientInit(self):
        shared = self.buffer[0]
        self.buffer = self.buffer[1:]
        # XXX react to shared
        # XXX send serverInit
        self._handler = self._handle_protocol, 1

    def _handle_protocol(self):
        ptype = unpack('!B', self.buffer[0])[0]
        nbytes = TYPE_LEN.get(ptype, 0)
        if len(self.buffer) < nbytes:
            self._handler = self._handle_protocol, nbytes + 1
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

    def setTcpNoDelay(self, enabled):
        return


class VNCLoggingClient(VNCDoToolClient):
    """ Specialization of a VNCDoToolClient that will save screen captures
    """
    capture_file = None

    def commitUpdate(self, rectangles):
        if self.capture_file:
            self.screen.save(self.capture_file)
            self.recorder('expect %s\n' % self.capture_file)
            self.capture_file = None


class VNCLoggingClientProxy(portforward.ProxyClient):
    """ Accept data from a server and forward to logger and downstream client

    vnc server -> VNCLoggingClientProxy -> vnc client
                                        -> VNCLoggingClient
    """
    vnclog = None
    ncaptures = 0

    def startLogging(self, peer):
        self.vnclog = VNCLoggingClient()
        self.vnclog.transport = NullTransport()
        self.vnclog.factory = self.peer.factory
        self.vnclog.recorder = peer.recorder
        # XXX double call to connectionMade?
        self.vnclog.connectionMade()
        self.vnclog._handler = self.vnclog._handleExpected
        self.vnclog.expect(self.vnclog._handleServerInit, 24)

    def dataReceived(self, data):
        portforward.ProxyClient.dataReceived(self, data)
        if self.vnclog:
            self.vnclog.dataReceived(data)


class VNCLoggingClientFactory(portforward.ProxyClientFactory):
    protocol = VNCLoggingClientProxy


class VNCLoggingServerProxy(portforward.ProxyServer, RFBServer):
    """ Proxy in the Middle, decodes and logs RFB messages before sending them upstream

    vnc client -> VNCLoggingServerProxy -> vnc server
                                        -> RFBServer
    """
    clientProtocolFactory = VNCLoggingClientFactory

    server = None
    buttons = 0
    recorder = None

    def connectionMade(self):
        log.info('new connection from %s', self.transport.getPeer().host)
        portforward.ProxyServer.connectionMade(self)
        RFBServer.connectionMade(self)
        self.mouse = (None, None)
        self.last_event = time.time()
        self.recorder = self.factory.getRecorder()

    def connectionLost(self, reason):
        portforward.ProxyServer.connectionLost(self, reason)
        self.factory.clientConnectionLost(self)

    def dataReceived(self, data):
        RFBServer.dataReceived(self, data)
        portforward.ProxyServer.dataReceived(self, data)

    def _handle_clientInit(self):
        RFBServer._handle_clientInit(self)
        self.peer.startLogging(self)

    def handle_keyEvent(self, key, down):
        now = time.time()

        if key in REVERSE_MAP:
            key = REVERSE_MAP[key]
        else:
            key = chr(key)

        cmds = ['pause', '%.4f' % (now - self.last_event)]
        self.last_event = now
        if down:
            cmds += 'keydown', key
        else:
            cmds += 'keyup', key
        cmds.append('\n')
        self.recorder(' '.join(cmds))

    def handle_pointerEvent(self, x, y, buttonmask):
        now = time.time()

        cmds = ['pause', '%.4f' % (now - self.last_event)]
        self.last_event = now
        if self.mouse != (x, y):
            cmds.append('move %d %d' % (x, y))
            self.mouse = x, y

        for button in range(1, 9):
            if buttonmask & (1 << (button - 1)):
                cmds.append('click %d' % button)
        cmds.append('\n')
        self.recorder(' '.join(cmds))


class VNCLoggingServerFactory(portforward.ProxyFactory):
    protocol = VNCLoggingServerProxy
    shared = True
    pseudocursor = False
    nocursor = False
    password_required = False

    output = sys.stdout
    _out = None

    def getRecorder(self):
        try:
            return self.output.write
        except AttributeError:
            now = time.strftime('%y%m%d-%H%M%S')
            outfile = os.path.join(self.output, '%s.vdo' % now)
            self._out = open(outfile, 'w')
            return self._out.write

    def clientConnectionMade(self, client):
        pass

    def clientConnectionLost(self, client):
        if self._out:
            self._out.close()
            self._out = None
