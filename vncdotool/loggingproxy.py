from struct import unpack
import sys
import time
import os.path
import logging
from typing import IO, Callable, List, Optional, Sequence, Tuple, Union

from twisted.protocols import portforward
from twisted.internet.protocol import Protocol
from twisted.python.failure import Failure

from .client import VNCDoToolClient, KEYMAP
from .rfb import Rect


log = logging.getLogger('proxy')

TYPE_LEN = {
    0: 20,
    2: 4,
    3: 10,
    4: 8,
    5: 6,
}

REVERSE_MAP = {v: n for (n, v) in KEYMAP.items()}


class RFBServer(Protocol):  # type: ignore[misc]
    _handler: Tuple[Callable[..., None], int] = (lambda data: None, 0)

    def connectionMade(self) -> None:
        Protocol.connectionMade(self)
        self.transport.setTcpNoDelay(True)

        self.buffer = bytearray()
        # XXX send version message
        self._handler = self._handle_version, 12

    def dataReceived(self, data: bytes) -> None:
        self.buffer += data
        while len(self.buffer) >= self._handler[1]:
            self._handler[0]()

    def _handle_version(self) -> None:
        msg = self.buffer[:12]
        del self.buffer[:12]
        if not msg.startswith(b'RFB 003.') and msg.endswith(b'\n'):
            self.transport.loseConnection()

        version = msg[8:11]
        if version in (b'003', b'005'):
            if self.factory.password_required:
                self._handler = self._handle_VNCAuthResponse, 16
            else:
                self._handler = self._handle_clientInit, 1
        elif version in (b'007', b'008'):
            # XXX send security v3.7+
            self._handler = self._handle_security, 1

    def _handle_security(self) -> None:
        # sectype = self.buffer[0]
        del self.buffer[:1]

    def _handle_VNCAuthResponse(self) -> None:
        del self.buffer[:16]
        self._handler = self._handle_clientInit, 1

    def _handle_clientInit(self) -> None:
        # shared = self.buffer[0]
        del self.buffer[:1]
        # XXX react to shared
        # XXX send serverInit
        self._handler = self._handle_protocol, 1

    def _handle_protocol(self) -> None:
        ptype, = unpack('!B', self.buffer[:1])
        nbytes = TYPE_LEN.get(ptype, 0)
        if len(self.buffer) < nbytes:
            self._handler = self._handle_protocol, nbytes + 1
            return

        block = bytes(self.buffer[1:nbytes])
        del self.buffer[:nbytes]
        if ptype == 0:
            args = unpack('!xxxBBBBHHHBBBxxx', block)
            self.handle_setPixelFormat(*args)
        elif ptype == 2:
            nencodings = unpack('!xH', block)[0]
            nbytes = 4 * nencodings
            encodings = unpack('!' + 'I' * nencodings, self.buffer[:nbytes])
            del self.buffer[:nbytes]
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

    def handle_setPixelFormat(self, bbp: int, depth: int, bigendian: bool, truecolor: bool, rmax: int, gmax: int, bmax: int, rshift: int, gshift: int, bshift: int) -> None:
        pass

    def handle_setEncodings(self, encodings: Sequence[int]) -> None:
        pass

    def handle_framebufferUpdate(self, x: int, y: int, w: int, h: int, incremental: bool) -> None:
        pass

    def handle_keyEvent(self, key: int, down: bool) -> None:
        pass

    def handle_pointerEvent(self, x: int, y: int, buttonmask: int) -> None:
        pass

    def handle_clientCutText(self, block: bytes) -> None:
        pass


class NullTransport:

    def write(self, data: bytes) -> None:
        return

    def writeSequence(self, data: bytes) -> None:
        return

    def setTcpNoDelay(self, enabled: bool) -> None:
        return


class VNCLoggingClient(VNCDoToolClient):
    """ Specialization of a VNCDoToolClient that will save screen captures
    """
    capture_file: Optional[str] = None

    def commitUpdate(self, rectangles: Optional[List[Rect]] = None) -> None:
        if self.capture_file:
            assert self.screen is not None
            self.screen.save(self.capture_file)
            self.recorder('expect %s\n' % self.capture_file)
            self.capture_file = None


class VNCLoggingClientProxy(portforward.ProxyClient):  # type: ignore[misc]
    """ Accept data from a server and forward to logger and downstream client

    vnc server -> VNCLoggingClientProxy -> vnc client
                                        -> VNCLoggingClient
    """
    vnclog: Optional[VNCLoggingClient] = None
    ncaptures = 0

    def startLogging(self, peer: "VNCLoggingServerProxy") -> None:
        self.vnclog = VNCLoggingClient()
        self.vnclog.transport = NullTransport()
        self.vnclog.factory = self.peer.factory
        self.vnclog.recorder = peer.recorder
        # XXX double call to connectionMade?
        self.vnclog.connectionMade()
        self.vnclog._handler = self.vnclog._handleExpected
        self.vnclog.expect(self.vnclog._handleServerInit, 24)

    def dataReceived(self, data: bytes) -> None:
        portforward.ProxyClient.dataReceived(self, data)
        if self.vnclog:
            self.vnclog.dataReceived(data)


class VNCLoggingClientFactory(portforward.ProxyClientFactory):  # type: ignore[misc]
    protocol = VNCLoggingClientProxy


class VNCLoggingServerProxy(portforward.ProxyServer, RFBServer):  # type: ignore[misc]
    """ Proxy in the Middle, decodes and logs RFB messages before sending them upstream

    vnc client -> VNCLoggingServerProxy -> vnc server
                                        -> RFBServer
    """
    clientProtocolFactory = VNCLoggingClientFactory

    server: Optional[str] = None
    buttons = 0
    recorder: Optional[Callable[[str], int]] = None

    def connectionMade(self) -> None:
        log.info('new connection from %s', self.transport.getPeer().host)
        portforward.ProxyServer.connectionMade(self)
        RFBServer.connectionMade(self)
        self.mouse: Tuple[Optional[int], Optional[int]] = (None, None)
        self.last_event = time.time()
        self.recorder = self.factory.getRecorder()

    def connectionLost(self, reason: Failure) -> None:
        portforward.ProxyServer.connectionLost(self, reason)
        self.factory.clientConnectionLost(self)

    def dataReceived(self, data: bytes) -> None:
        RFBServer.dataReceived(self, data)
        portforward.ProxyServer.dataReceived(self, data)

    def _handle_clientInit(self) -> None:
        RFBServer._handle_clientInit(self)
        self.peer.startLogging(self)

    def handle_keyEvent(self, key: int, down: bool) -> None:
        now = time.time()

        rev = REVERSE_MAP.get(key, chr(key))

        cmds = ['pause', '%.4f' % (now - self.last_event)]
        self.last_event = now
        if down:
            cmds += 'keydown', rev
        else:
            cmds += 'keyup', rev
        cmds.append('\n')
        assert self.recorder is not None
        self.recorder(' '.join(cmds))

    def handle_pointerEvent(self, x: int, y: int, buttonmask: int) -> None:
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
        assert self.recorder is not None
        self.recorder(' '.join(cmds))


class VNCLoggingServerFactory(portforward.ProxyFactory):  # type: ignore[misc]
    protocol = VNCLoggingServerProxy
    shared = True
    pseudocursor = False
    nocursor = False
    password_required = False

    output: Union[IO[str], str] = sys.stdout
    _out: Optional[IO[str]] = None

    def getRecorder(self) -> Callable[[str], int]:
        if isinstance(self.output, str):
            now = time.strftime('%y%m%d-%H%M%S')
            outfile = os.path.join(self.output, '%s.vdo' % now)
            self._out = open(outfile, 'w')
            return self._out.write
        else:
            return self.output.write

    def clientConnectionMade(self, client: VNCLoggingServerProxy) -> None:
        pass

    def clientConnectionLost(self, client: VNCLoggingServerProxy) -> None:
        if self._out:
            self._out.close()
            self._out = None
