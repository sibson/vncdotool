"""
RFB protocol implementattion, client side.

Override :class:`RFBClient` and :class:`RFBFactory` in your application.
See vncviewer.py for an example.

Reference:
https://www.rfc-editor.org/rfc/rfc6143
https://github.com/rfbproto/rfbproto/blob/master/rfbproto.rst
"""
# (C) 2003 cliechti@gmx.net
#
# MIT License

from __future__ import annotations

import functools
import getpass
import sys
import warnings
import zlib
from struct import error as StructError, pack, unpack
from typing import (
    Any,
    Callable,
    Collection,
    Generator,
    Tuple,
)

from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
from cryptography.hazmat.primitives.ciphers import Cipher, modes
from twisted.application import internet, service
from twisted.internet import protocol
from twisted.internet.interfaces import IConnector, ITransport
from twisted.internet.protocol import Protocol
from twisted.python import log, usage
from twisted.python.failure import Failure

from . import decoders, messages, security
from .const import Encoding, AuthTypes, FenceFlags, MsgC2S, MsgS2C
from .keys import Key
from .pixelformat import PixelFormat

Ver = Tuple[int, int]

_DECODE_ERRORS = (decoders.DecodeError, StructError, MemoryError, zlib.error)
_SECURITY_ERRORS = (security.SecurityError, StructError)

# ~ from twisted.internet import reactor


class RFBClient(Protocol):
    # https://www.rfc-editor.org/rfc/rfc6143#section-7.1.1
    SUPPORTED_SERVER_VERSIONS = {
        (3, 3),
        # (3, 5),
        (3, 7),
        (3, 8),
        (3, 889),  # Apple Remote Desktop
        (4, 0),  # Intel AMT KVM
        (4, 1),  # RealVNC 4.6
        (5, 0),  # RealVNC 5.3
    }
    MAX_CLIENT_VERSION = (3, 8)
    SUPPORTED_AUTHS = set(security.HANDLERS)
    _UNMIGRATED_ENCODINGS = {
        Encoding.ZRLE,
        Encoding.PSEUDO_LAST_RECT,
    }
    SUPPORTED_ENCODINGS = set(decoders.DECODERS) | _UNMIGRATED_ENCODINGS

    # Greater than any u16 dimension, so it refuses nothing until a subclass
    # narrows it.
    MAX_DESKTOP_SIZE = 0x10000

    MAX_MESSAGE_PAYLOAD = 1 << 20

    _HEADER = b"RFB 000.000\n"
    _HEADER_TRANSLATE = bytes.maketrans(b"0123456789", b"0" * 10)

    _CHANGING_HOOKS = ("fillRectangle", "updateRectangle")

    transport: ITransport

    _challenge: bytes

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for name in cls._CHANGING_HOOKS:
            if not getattr(cls, name).__module__.startswith("vncdotool."):
                warnings.warn(
                    f"{name} changed in 2.0; comment "
                    "on https://github.com/sibson/vncdotool/issues/385 if "
                    "you can't migrate",
                    FutureWarning,
                    stacklevel=2,
                )

    def __init__(self) -> None:
        self._packet = bytearray()
        self._handler = self._handleInitial
        self._expected_len = 12
        self._expected_args: tuple[Any, ...] = ()
        self._expected_kwargs: dict[str, Any] = {}
        self._already_expecting = False
        self._aborted = False
        self._version: Ver = (0, 0)
        self._version_server: Ver = (0, 0)
        self.negotiated_encodings = {
            Encoding.RAW,
        }
        self.pixel_format = PixelFormat()
        self.width = 0
        self.height = 0
        self._rect_backing = bytearray()
        self._decoders = decoders.for_connection()
        self._messages = messages.for_connection()
        self._security = security.for_connection()

    @property
    def bypp(self) -> int:
        return self.pixel_format.bypp

    # ------------------------------------------------------
    # states used on connection startup
    # ------------------------------------------------------

    def _handleInitial(self) -> None:
        head = self._packet[:12]
        norm = head.translate(self._HEADER_TRANSLATE)
        if norm == self._HEADER:
            version_server = (int(head[4:7]), int(head[8:11]))
            if version_server not in self.SUPPORTED_SERVER_VERSIONS:
                log.msg("Protocol version %d.%d not supported" % version_server)

            version = max(
                v for v in self.SUPPORTED_SERVER_VERSIONS if v <= version_server
            )
            if version > self.MAX_CLIENT_VERSION:
                version = self.MAX_CLIENT_VERSION

            del self._packet[0:12]
            log.msg("Using protocol version %d.%d" % version)
            self.transport.write(b"RFB %03d.%03d\n" % version)
            self._handler = self._handleExpected
            self._version = version
            self._version_server = version_server
            if version < (3, 7):
                self.expect(self._handleAuth, 4)
            else:
                self.expect(self._handleNumberSecurityTypes, 1)
        elif not self._HEADER.startswith(norm):
            self.abortConnection(f"invalid initial server response {head!r}")

    def _handleNumberSecurityTypes(self, block: bytes) -> None:
        (num_types,) = unpack("!B", block)
        if num_types:
            self.expect(self._handleSecurityTypes, num_types)
        else:
            self.expect(self._handleConnFailed, 4)

    def _handleSecurityTypes(self, block: bytes) -> None:
        types = unpack(f"!{len(block)}B", block)
        for sec_type in types:
            log.msg(f"Offered {AuthTypes.lookup(sec_type)!r}")
        valid_types = set(types) & self.SUPPORTED_AUTHS
        if valid_types:
            sec_type = max(valid_types)
            self.transport.write(pack("!B", sec_type))
            self._startSecurity(sec_type)
        else:
            self.abortConnection(f"unknown security types: {types!r}")

    def _handleAuth(self, block: bytes) -> None:
        (auth,) = unpack("!I", block)
        # ~ print(f"{auth=}")
        if auth == AuthTypes.INVALID:
            self.expect(self._handleConnFailed, 4)
        elif auth in self._security:
            # Before 3.7 the server dictates the security type, so the client
            # writes nothing to choose it.
            self._startSecurity(auth)
        else:
            self.abortConnection(f"unknown auth response {AuthTypes.lookup(auth)!r}")

    def _startSecurity(self, sec_type: int) -> None:
        handler = self._security.get(sec_type)
        if handler is None:
            self.abortConnection(
                f"unsupported security type {AuthTypes.lookup(sec_type)!r}"
            )
            return
        self._pump(
            None,
            handler.handle(self),
            self._finishSecurity,
            f"the {AuthTypes.lookup(sec_type)!r} security type",
            _SECURITY_ERRORS,
            "negotiate",
        )

    def _finishSecurity(self, proceed: bool) -> None:
        if proceed:
            self._doClientInitialization()

    def _handleConnFailed(self, block: bytes) -> None:
        (waitfor,) = unpack("!I", block)
        self.expect(self._handleConnMessage, waitfor)

    def _handleConnMessage(self, block: bytes) -> None:
        self.abortConnection(f"Connection refused: {block!r}")

    def ardRequestCredentials(self) -> None:
        if self.factory.username is None:
            self.factory.username = input("username: ")
        if self.factory.password is None:
            self.factory.password = getpass.getpass("password:")

    def sendPassword(self, password: str) -> None:
        """send password"""
        self.transport.write(des_encrypt(_vnc_des(password), self._challenge))

    def _doClientInitialization(self) -> None:
        self.transport.write(pack("!B", self.factory.shared))
        self.expect(self._handleServerInit, 24)

    def _handleServerInit(self, block: bytes) -> None:
        (self.width, self.height, pixformat, namelen) = unpack("!HH16sI", block)
        self.pixel_format = PixelFormat.from_bytes(pixformat)
        log.msg(f"Native {self.pixel_format} bytes={self.pixel_format.bypp}")
        self.expect(self._handleServerName, namelen)

    def _handleServerName(self, block: bytes) -> None:
        self.name = block
        # callback:
        self.vncConnectionMade()
        self.expect(self._handleConnection, 1)

    # ------------------------------------------------------
    # Server to client messages
    # ------------------------------------------------------
    def _handleConnection(self, block: bytes) -> None:
        (msgid,) = unpack("!B", block)
        if msgid == MsgS2C.FRAMEBUFFER_UPDATE:
            self.expect(self._handleFramebufferUpdate, 3)
            return
        handler = self._messages.get(msgid)
        if handler is None:
            self.abortConnection(f"unknown message received {MsgS2C.lookup(msgid)!r}")
            return
        self._pump(
            None,
            handler.handle(self),
            self._finishMessage,
            f"the {MsgS2C.lookup(msgid)!r} message",
        )

    def _finishMessage(self, _outcome: None) -> None:
        self.expect(self._handleConnection, 1)

    def _handleFramebufferUpdate(self, block: bytes) -> None:
        (self.rectangles,) = unpack("!xH", block)
        self.rectanglePos: list[tuple[int, int, int, int]] = []
        self.beginUpdate()
        self._doConnection()

    def _doConnection(self) -> None:
        if self.rectangles:
            self.expect(self._handleRectangle, 12)
        else:
            self.commitUpdate(self.rectanglePos)
            self.expect(self._handleConnection, 1)

    def _handleRectangle(self, block: bytes) -> None:
        (x, y, width, height, encoding) = unpack("!HHHHi", block)
        if encoding == Encoding.PSEUDO_LAST_RECT:
            self.rectangles = 0

        if self.rectangles:
            self.rectangles -= 1
            decoder = self._decoders.get(encoding)
            if decoder is not None:
                self._pumpRectangle(decoder, x, y, width, height)
            else:
                self.abortConnection(
                    f"unknown encoding received {Encoding.lookup(encoding)!r}"
                )
        else:
            self._doConnection()

    def _pumpRectangle(
        self, decoder: decoders.Decoder, x: int, y: int, width: int, height: int
    ) -> None:
        rect = (x, y, width, height)
        self._pump(
            None,
            decoder.decode(self, rect, self.pixel_format),
            functools.partial(self._finishRectangle, rect),
            "this rectangle",
        )

    def _finishRectangle(
        self, rect: tuple[int, int, int, int], outcome: decoders.Outcome
    ) -> None:
        paste = outcome.paste
        if paste is not None:
            pixels, output_format = paste
            x, y, width, height = rect
            expected = width * height * output_format.bypp
            if len(pixels) != expected:
                self.abortConnection(
                    f"decoder produced {len(pixels)} bytes for a "
                    f"{width}x{height} rectangle at {output_format.bypp} "
                    f"bytes per pixel, which needs {expected}"
                )
                return
            self.updateRectangle(x, y, width, height, pixels, output_format)
        if outcome.changed:
            self.rectanglePos.append(rect)
        self._doConnection()

    # ---  what a decoder may ask of the pump

    def requireFits(self, width: int, height: int) -> None:
        """Raise unless a rectangle fits the framebuffer."""
        limit_w = self.width or self.MAX_DESKTOP_SIZE
        limit_h = self.height or self.MAX_DESKTOP_SIZE
        if not (0 <= width <= limit_w and 0 <= height <= limit_h):
            raise decoders.DecodeError(
                f"{width}x{height} does not fit a {limit_w}x{limit_h} framebuffer"
            )

    def rectBuffer(self, width: int, height: int) -> decoders.RectBuffer:
        """A buffer for one rectangle, reused across rectangles."""
        self.requireFits(width, height)
        needed = width * height * self.bypp
        try:
            if len(self._rect_backing) < needed:
                self._rect_backing = bytearray(needed)
        except MemoryError:
            raise decoders.DecodeError(f"no memory for a {width}x{height} rectangle")
        return decoders.RectBuffer(width, height, self.bypp, self._rect_backing)

    def requirePayload(self, length: int) -> None:
        """Raise unless a server-declared message payload fits the bound."""
        if length > self.MAX_MESSAGE_PAYLOAD:
            raise decoders.DecodeError(
                f"payload of {length} bytes exceeds the {self.MAX_MESSAGE_PAYLOAD} "
                "byte limit"
            )

    def _pump(
        self,
        block: bytes | None,
        generator: Generator[int, Any, Any],
        on_done: Callable[[Any], None],
        describe: str,
        errors: tuple[type[BaseException], ...] = _DECODE_ERRORS,
        verb: str = "decode",
    ) -> None:
        try:
            size = generator.send(block)
        except StopIteration as stop:
            on_done(stop.value)
            return
        except errors as exc:
            generator.close()
            self.abortConnection(f"cannot {verb} {describe}: {exc}")
            return

        if size < 0:
            generator.close()
            self.abortConnection(f"decoder asked for {size} bytes")
            return
        self.expect(self._pump, size, generator, on_done, describe, errors, verb)

    # ------------------------------------------------------
    # incomming data redirector
    # ------------------------------------------------------
    def dataReceived(self, data: bytes) -> None:
        if self._aborted:
            return
        self._packet.extend(data)
        self._handler()

    def _handleExpected(self) -> None:
        if len(self._packet) >= self._expected_len:
            # `expect` is the only thing that re-arms the parked handler, so
            # a handler that gives up without calling it would be re-entered
            # by this loop with the next block.
            while len(self._packet) >= self._expected_len and not self._aborted:
                self._already_expecting = True
                block = bytes(self._packet[: self._expected_len])
                del self._packet[: self._expected_len]
                # ~ log.msg(f"handle {block!r} with {self._expected_handler.__name__!r}")
                self._expected_handler(
                    block, *self._expected_args, **self._expected_kwargs
                )
            self._already_expecting = False

    def abortConnection(self, reason: str) -> None:
        """Report a protocol failure and stop parsing for good.

        loseConnection is asynchronous and bytes already buffered are still
        delivered, so the parser has to be stopped here as well.
        """
        self._aborted = True
        self._packet.clear()
        self.vncProtocolError(reason)
        self.transport.loseConnection()

    def expect(
        self, handler: Callable[..., None], size: int, *args: Any, **kwargs: Any
    ) -> None:
        # ~ log.msg(f"expect({handler.__name__!r}, {size!r}, {args!r}, {kwargs!r})")
        self._expected_handler = handler
        self._expected_len = size
        self._expected_args = args
        self._expected_kwargs = kwargs
        if not self._already_expecting:
            self._handleExpected()  # just in case that there is already enough data

    # ------------------------------------------------------
    # client -> server messages
    # ------------------------------------------------------

    def setPixelFormat(self, pixel_format: PixelFormat) -> None:
        log.msg(f"Requesting {pixel_format}")
        pixformat = pixel_format.to_bytes()
        self.transport.write(pack("!Bxxx16s", MsgC2S.SET_PIXEL_FORMAT, pixformat))
        self.pixel_format = pixel_format

    def setEncodings(self, list_of_encodings: Collection[Encoding]) -> None:
        self.transport.write(pack("!BxH", MsgC2S.SET_ENCODING, len(list_of_encodings)))
        for encoding in list_of_encodings:
            log.msg(f"Offering {encoding!r}")
            self.transport.write(pack("!i", encoding))
        self.encodingsOffered(frozenset(list_of_encodings))

    def encodingsOffered(self, encodings: frozenset[Encoding]) -> None:
        for decoder in self._decoders.values():
            decoder.encodingsOffered(encodings)

    def framebufferUpdateRequest(
        self,
        x: int = 0,
        y: int = 0,
        width: int | None = None,
        height: int | None = None,
        incremental: bool = False,
    ) -> None:
        if width is None:
            width = self.width - x
        if height is None:
            height = self.height - y
        self.transport.write(pack("!BBHHHH", MsgC2S.FRAMEBUFFER_UPDATE_REQUEST, incremental, x, y, width, height))

    def keyEvent(self, key: Key | int, down: bool = True) -> None:
        """For most ordinary keys, the "keysym" is the same as the corresponding ASCII value.
        Other common keys are shown in the ``Key`` constants."""
        self.transport.write(pack("!BBxxI", MsgC2S.KEY_EVENT, down, key))

    def pointerEvent(self, x: int, y: int, buttonmask: int = 0) -> None:
        """Indicates either pointer movement or a pointer button press or release. The pointer is
        now at (x-position, y-position), and the current state of buttons 1 to 8 are represented
        by bits 0 to 7 of button-mask respectively, 0 meaning up, 1 meaning down (pressed).
        """
        self.transport.write(pack("!BBHH", MsgC2S.POINTER_EVENT, buttonmask, x, y))

    def clientCutText(self, message: str) -> None:
        """The client has new ISO 8859-1 (Latin-1) text in its cut buffer.
        (aka clipboard)
        """
        data = message.encode("iso-8859-1")
        self.transport.write(pack("!BxxxI", MsgC2S.CLIENT_CUT_TEXT, len(data)) + data)

    def clientFence(self, flags: FenceFlags, payload: bytes = b"") -> None:
        """Request, or respond to, a Fence synchronisation of the data stream."""
        self.transport.write(pack("!BxxxIB", MsgC2S.CLIENT_FENCE, flags, len(payload)) + payload)

    # ------------------------------------------------------
    # callbacks
    # override these in your application
    # ------------------------------------------------------
    def vncConnectionMade(self) -> None:
        """connection is initialized and ready.
        typicaly, the pixel format is set here."""

    def vncRequestPassword(self) -> None:
        """a password is needed to log on, use :meth:`sendPassword` to
        send one."""
        if self.factory.password is None:
            log.msg("need a password")
            self.transport.loseConnection()
            return
        self.sendPassword(self.factory.password)

    def vncAuthFailed(self, reason: Failure) -> None:
        """called when the authentication failed.
        the connection is closed."""
        log.msg(f"Cannot connect {reason}")

    def vncProtocolError(self, reason: str) -> None:
        """called when the server sends something we cannot handle.
        the connection is closed."""
        log.msg(reason)

    def beginUpdate(self) -> None:
        """called before a series of :meth:`updateRectangle`,
        :meth:`copyRectangle` or :meth:`fillRectangle`."""

    def commitUpdate(self, rectangles: list[tuple[int, int, int, int]] | None = None) -> None:
        """called after a series of :meth:`updateRectangle`, :meth:`copyRectangle`
        or :meth:`fillRectangle` are finished.

        Typicaly, here is the place to request the next screen
        update with :meth:`framebufferUpdateRequest` with ``incremental=True``.

        :param rectangles: a list of tuples (x,y,w,h) with the updated rectangles.
        """

    def updateRectangle(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        data: bytes,
        pixel_format: PixelFormat,
    ) -> None:
        """new bitmap data.

        :param data: bytes in `pixel_format`, which is the negotiated format
            for every encoding in use today but need not be.
        """

    def copyRectangle(
        self, srcx: int, srcy: int, x: int, y: int, width: int, height: int
    ) -> None:
        """used for copyrect encoding. copy the given rectangle
        (src, srxy, width, height) to the target coords (x,y)"""

    def fillRectangle(
        self, x: int, y: int, width: int, height: int, color: bytes
    ) -> None:
        """fill the area with the color.

        :param color: bytes in the pixel format set up earlier.
        """
        # fallback variant, use update recatngle
        # override with specialized function for better performance
        self.updateRectangle(
            x, y, width, height, color * width * height, self.pixel_format
        )

    def updateCursor(
        self, x: int, y: int, width: int, height: int, image: bytes, mask: bytes
    ) -> None:
        """New cursor, focuses at (x, y)"""

    def updateDesktopSize(self, width: int, height: int) -> None:
        """New desktop size of width*height."""

    def set_color_map(self, first: int, colors: list[tuple[int, int, int]]) -> None:
        """The server is using a new color map."""

    def bell(self) -> None:
        """bell"""

    def copy_text(self, text: str) -> None:
        """The server has new ISO 8859-1 (Latin-1) text in its cut buffer.
        (aka clipboard)"""


class RFBFactory(protocol.ClientFactory):
    """A factory for remote frame buffer connections."""

    # the class of the protocol to build
    # should be overriden by application to use a derrived class
    protocol = RFBClient

    username: str | None = None

    def __init__(self, password: str | None = None, shared: bool = False) -> None:
        self.password = password
        self.shared = shared


def des_encrypt(key: bytes, data: bytes) -> bytes:
    """Encrypt with single DES, as the VNC family's password handling uses.

    Single DES in ECB is weak, and is what RFB specifies: both the
    authentication challenge response (RFC 6143 section 7.2.2) and the
    password file format are defined in terms of it, so a stronger
    algorithm here would simply fail to talk to any VNC server."""
    # Triple-DES with the same 56-bit key repeated three times is
    # equivalent to single-DES. Passing the 8-byte key directly is deprecated
    # upstream; only 24-byte keys will be accepted in a future release.
    encryptor = Cipher(TripleDES(key * 3), modes.ECB()).encryptor()
    return encryptor.update(data) + encryptor.finalize()


def reverse_bits(data: bytes) -> bytes:
    """The bit-reversal the VNC family applies to a DES key before using it,
    both for the authentication challenge response here and for the
    password obfuscation in ~/.vnc/passwd files."""
    return bytes(
        sum((128 >> i) if (k & (1 << i)) else 0 for i in range(8)) for k in data
    )


def _vnc_des(password: str) -> bytes:
    """Custom DES variant for RFB protocol.

    RFB protocol for authentication requires client to encrypt
    challenge sent by server with password using DES method. However,
    bits in each byte of the password are put in reverse order before
    using it as encryption key."""
    pw = f"{password:\0<8.8}"  # make sure its 8 chars long, zero padded
    key = pw.encode(
        "ASCII"
    )  # unspecified https://www.rfc-editor.org/rfc/rfc6143#section-7.2.2
    return reverse_bits(key)


# --- test code only, see vncviewer.py

if __name__ == "__main__":

    class RFBTest(RFBClient):
        """dummy client"""

        def vncConnectionMade(self) -> None:
            print(f"Screen format: {self.pixel_format}")
            print(f"Desktop name: {self.name!r}")
            self.setEncodings([Encoding.RAW])
            self.framebufferUpdateRequest()

        def updateRectangle(
            self,
            x: int,
            y: int,
            width: int,
            height: int,
            data: bytes,
            pixel_format: PixelFormat,
        ) -> None:
            print("%s " * 5 % (x, y, width, height, repr(data[:20])))

    class RFBTestFactory(protocol.ClientFactory):
        """test factory"""

        protocol = RFBTest

        def clientConnectionLost(self, connector: IConnector, reason: Failure) -> None:
            print(reason)
            from twisted.internet import reactor

            reactor.stop()
            # ~ connector.connect()

        def clientConnectionFailed(
            self, connector: IConnector, reason: Failure
        ) -> None:
            print("connection failed:", reason)
            from twisted.internet import reactor

            reactor.stop()

    class Options(usage.Options):
        """command line options"""

        optParameters = [
            ["display", "d", "0", "VNC display"],
            ["host", "h", "localhost", "remote hostname"],
            ["outfile", "o", None, "Logfile [default: sys.stdout]"],
        ]

    o = Options()
    try:
        o.parseOptions()
    except usage.UsageError as errortext:
        print(f"{sys.argv[0]}: {errortext}")
        print(f"{sys.argv[0]}: Try --help for usage details.")
        raise SystemExit(1)

    logFile = sys.stdout
    if o.opts["outfile"]:
        logFile = o.opts["outfile"]
    log.startLogging(logFile)

    host = o.opts["host"]
    port = int(o.opts["display"]) + 5900

    application = service.Application("rfb test")  # create Application

    # connect to this host and port, and reconnect if we get disconnected
    vncClient = internet.TCPClient(host, port, RFBFactory())  # create the service
    vncClient.setServiceParent(application)

    # this file should be run as 'twistd -y rfb.py' but it didn't work -
    # could't import crippled_des.py, so using this hack.
    # now with crippled_des.py replaced with pyDes this can be no more actual
    from twisted.internet import reactor

    vncClient.startService()
    reactor.run()


def __getattr__(name: str) -> Any:
    _, sep, key = name.partition("KEY_")
    if sep:
        warnings.warn(f"Deprecated use of {name}; use Keys.key.{key}", DeprecationWarning, stacklevel=2)
        return getattr(Key, key)
    raise AttributeError(f"module {__name__} has no attribute {name}")
