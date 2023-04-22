import logging
import os.path
import socket
import sys
import time
from struct import unpack, unpack_from
from typing import IO, Callable, List, Optional, Sequence, Tuple, Union

from twisted.internet.protocol import Protocol
from twisted.protocols import portforward
from twisted.python.failure import Failure

from .client import KEYMAP, VNCDoToolClient
from .rfb import AuthTypes, Encoding, IntEnumLookup, PixelFormat, Rect

log = logging.getLogger(__name__)


class ProtocolError(Exception):
    """VNC Protocol error"""


class MsgC2S(IntEnumLookup):
    """RFC 6143 §7.5. Client-to-Server Messages."""

    SET_PIXEL_FORMAT = 0
    SET_ENCODING = 2
    FRAMEBUFFER_UPDATE_REQUEST = 3
    KEY_EVENT = 4
    POINTER_EVENT = 5
    CLIENT_CUT_TEXT = 6
    FILE_TRANSFER = 7
    SET_SCALE = 8
    SET_SERVER_INPUT = 9
    SET_SW = 10
    TEXT_CHAT = 11
    KEY_FRAME_REquest = 12
    KEEP_ALIVE = 13
    ULTRA_14 = 14
    SET_SCALE_FACTOR = 15
    ULTRA_16 = 16
    ULTRA_17 = 17
    ULTRA_18 = 18
    ULTRA_19 = 19
    REQUEST_SESSION = 20
    SET_SESSION = 21
    NOTIFY_PLUGIN_STREAMING = 80
    VMWARE_127 = 127
    CAR_CONNECTIVITY = 128
    ENABLE_CONTINUOUS_UPDATES = 150
    CLIENT_FENCE = 248
    OLIVE_CALL_CONTROL = 249
    XVP_CLIENT_MESSAGE = 250
    SET_DESKTOP_SIZE = 251
    TIGHT = 252
    GII_CLIENT_MESSAGE = 253  # General Input Interface
    VMWARE_254 = 254
    QEMU_CLIENT_MESSAGE = 255


class QemuClientMessage(IntEnumLookup):
    """https://github.com/rfbproto/rfbproto/blob/master/rfbproto.rst#qemu-client-message"""

    EXTENDED_KEY_EVENT = 0
    AUDIO = 1


TYPE_LEN = {
    MsgC2S.SET_PIXEL_FORMAT: 20,
    MsgC2S.SET_ENCODING: 4,
    MsgC2S.FRAMEBUFFER_UPDATE_REQUEST: 10,
    MsgC2S.KEY_EVENT: 8,
    MsgC2S.POINTER_EVENT: 6,
    MsgC2S.QEMU_CLIENT_MESSAGE: 1,
}

REVERSE_MAP = {v: n for (n, v) in KEYMAP.items()}


class RFBServer(Protocol):  # type: ignore[misc]
    _handler: Tuple[Callable[..., None], int] = (lambda data: None, 0)

    def connectionMade(self) -> None:
        super().connectionMade()
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
        if not msg.startswith(b"RFB 003.") and msg.endswith(b"\n"):
            self.transport.loseConnection()

        version = msg[8:11]
        if version in (b"003", b"005"):
            if self.factory.password_required:
                self._handler = self._handle_VNCAuthResponse, 16
            else:
                self._handler = self._handle_clientInit, 1
        elif version in (b"007", b"008"):
            # XXX send security v3.7+
            self._handler = self._handle_security, 1

    def _handle_security(self) -> None:
        sectype = self.buffer[0]
        log.debug("Client selected %r", AuthTypes.lookup(sectype))
        del self.buffer[:1]
        self._handler = self._handle_clientInit, 1

    def _handle_VNCAuthResponse(self) -> None:
        del self.buffer[:16]
        self._handler = self._handle_clientInit, 1

    def _handle_clientInit(self) -> None:
        shared = self.buffer[0]
        log.debug("Client shares: %s", shared)
        del self.buffer[:1]
        # XXX react to shared
        # XXX send serverInit
        self._handler = self._handle_protocol, 1

    def _handle_protocol(self) -> None:
        (ptype,) = unpack_from("!B", self.buffer)
        nbytes = TYPE_LEN.get(ptype, 0)
        if len(self.buffer) < nbytes:
            self._handler = self._handle_protocol, nbytes + 1
            return

        block = bytes(self.buffer[1:nbytes])
        del self.buffer[:nbytes]
        if ptype == MsgC2S.SET_PIXEL_FORMAT:
            (args,) = unpack("!xxx16s", block)
            pixel_fomat = PixelFormat.from_bytes(args)
            self.handle_setPixelFormat(pixel_fomat)
        elif ptype == MsgC2S.SET_ENCODING:
            (nencodings,) = unpack("!xH", block)
            nbytes = 4 * nencodings
            encodings = unpack_from("!" + "I" * nencodings, self.buffer)
            del self.buffer[:nbytes]
            for encoding in encodings:
                log.debug(f"Client announces {Encoding.lookup(encoding)!r}")
            self.handle_setEncodings(encodings)
        elif ptype == MsgC2S.FRAMEBUFFER_UPDATE_REQUEST:
            inc, x, y, w, h = unpack("!BHHHH", block)
            self.handle_framebufferUpdate(x, y, w, h, inc)
        elif ptype == MsgC2S.KEY_EVENT:
            down, key = unpack("!BxxI", block)
            self.handle_keyEvent(key, down)
        elif ptype == MsgC2S.POINTER_EVENT:
            buttonmask, x, y = unpack("!BHH", block)
            self.handle_pointerEvent(x, y, buttonmask)
        elif ptype == MsgC2S.CLIENT_CUT_TEXT:
            self.handle_clientCutText(block)
        elif ptype == MsgC2S.QEMU_CLIENT_MESSAGE:
            (subtype,) = unpack("!B", block)
            if subtype == QemuClientMessage.EXTENDED_KEY_EVENT:
                self._handler = self._handle_qemuExtendedKeyEvent, 10
            else:
                log.debug("Unhandled subtype %r", QemuClientMessage.lookup(subtype))
                raise ProtocolError(subtype)
        else:
            log.debug("Unhandled response %r", MsgC2S.lookup(ptype))
            raise ProtocolError(ptype)

    def _handle_qemuExtendedKeyEvent(self) -> None:
        down_flag, keysym, keycode = unpack_from("!HII", self.buffer)
        del self.buffer[:12]
        self.handle_keyEventExtended(keysym, down_flag, keycode)
        self._handler = self._handle_protocol, 1

    def handle_setPixelFormat(self, pixel_format: PixelFormat) -> None:
        pass

    def handle_setEncodings(self, encodings: Sequence[int]) -> None:
        pass

    def handle_framebufferUpdate(
        self, x: int, y: int, w: int, h: int, incremental: bool
    ) -> None:
        pass

    def handle_keyEvent(self, key: int, down: bool) -> None:
        pass

    def handle_pointerEvent(self, x: int, y: int, buttonmask: int) -> None:
        pass

    def handle_clientCutText(self, block: bytes) -> None:
        pass

    def handle_keyEventExtended(self, keysym: int, down: bool, keycode: int) -> None:
        self.handle_keyEvent(keysym, down)


class NullTransport:
    addressFamily = socket.AF_UNSPEC

    def write(self, data: bytes) -> None:
        return

    def writeSequence(self, data: bytes) -> None:
        return

    def setTcpNoDelay(self, enabled: bool) -> None:
        return

    def loseConnection(self) -> None:
        return


class VNCLoggingClient(VNCDoToolClient):
    """Specialization of a VNCDoToolClient that will save screen captures"""

    capture_file: Optional[str] = None

    def commitUpdate(self, rectangles: Optional[List[Rect]] = None) -> None:
        if self.capture_file:
            assert self.screen is not None
            self.screen.save(self.capture_file)
            self.recorder("expect %s\n" % self.capture_file)
            self.capture_file = None


class VNCLoggingClientProxy(portforward.ProxyClient):  # type: ignore[misc]
    """Accept data from a server and forward to logger and downstream client

    VNC server -> VNCLoggingClientProxy -> VNC client
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
        super().dataReceived(data)
        if self.vnclog:
            self.vnclog.dataReceived(data)


class VNCLoggingClientFactory(portforward.ProxyClientFactory):  # type: ignore[misc]
    protocol = VNCLoggingClientProxy


class VNCLoggingServerProxy(portforward.ProxyServer, RFBServer):  # type: ignore[misc]
    """Proxy in the middle, decodes and logs RFB messages before sending them upstream

    VNC client -> VNCLoggingServerProxy -> VNC server
                                        -> RFBServer
    """

    clientProtocolFactory = VNCLoggingClientFactory

    server: Optional[str] = None
    buttons = 0
    recorder: Optional[Callable[[str], int]] = None

    def connectionMade(self) -> None:
        log.info("new connection from %s", self.transport.getPeer().host)
        super().connectionMade()
        RFBServer.connectionMade(self)
        self.mouse: Tuple[Optional[int], Optional[int]] = (None, None)
        self.last_event = time.time()
        self.recorder = self.factory.getRecorder()

    def connectionLost(self, reason: Failure) -> None:
        super().connectionLost(reason)
        self.factory.clientConnectionLost(self)

    def dataReceived(self, data: bytes) -> None:
        RFBServer.dataReceived(self, data)
        super().dataReceived(data)

    def _handle_clientInit(self) -> None:
        RFBServer._handle_clientInit(self)
        self.peer.startLogging(self)

    def handle_keyEvent(self, key: int, down: bool) -> None:
        now = time.time()

        rev = REVERSE_MAP.get(key, chr(key))

        cmds = ["pause", "%.4f" % (now - self.last_event)]
        self.last_event = now
        if down:
            cmds += "keydown", rev
        else:
            cmds += "keyup", rev
        cmds.append("\n")
        assert self.recorder is not None
        self.recorder(" ".join(cmds))

    def handle_pointerEvent(self, x: int, y: int, buttonmask: int) -> None:
        now = time.time()

        cmds = ["pause", "%.4f" % (now - self.last_event)]
        self.last_event = now
        if self.mouse != (x, y):
            cmds.append("move %d %d" % (x, y))
            self.mouse = x, y

        for button in range(1, 9):
            if buttonmask & (1 << (button - 1)):
                cmds.append("click %d" % button)
        cmds.append("\n")
        assert self.recorder is not None
        self.recorder(" ".join(cmds))


class VNCLoggingServerFactory(portforward.ProxyFactory):  # type: ignore[misc]
    protocol = VNCLoggingServerProxy
    shared = True

    pseudocursor = False
    nocursor = False
    pseudodesktop = True
    qemu_extended_key = True
    last_rect = True
    force_caps = False

    password_required = False

    output: Union[IO[str], str] = sys.stdout
    _out: Optional[IO[str]] = None

    def getRecorder(self) -> Callable[[str], int]:
        if isinstance(self.output, str):
            now = time.strftime("%y%m%d-%H%M%S")
            outfile = os.path.join(self.output, "%s.vdo" % now)
            self._out = open(outfile, "w")
            return self._out.write
        else:
            return self.output.write

    def clientConnectionMade(self, client: VNCLoggingServerProxy) -> None:
        pass

    def clientConnectionLost(self, client: VNCLoggingServerProxy) -> None:
        if self._out:
            self._out.close()
            self._out = None
