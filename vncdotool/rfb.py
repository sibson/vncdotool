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

import getpass
import sys
import warnings
import zlib
from dataclasses import astuple, dataclass
from struct import Struct, error as StructError, pack, unpack, unpack_from
from typing import (
    Any,
    Callable,
    ClassVar,
    Collection,
    Iterator,
    List,
    Tuple,
    cast,
)

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.asymmetric import dh
from cryptography.hazmat.primitives import hashes
from cryptography.utils import CryptographyDeprecationWarning
from twisted.application import internet, service
from twisted.internet import protocol
from twisted.internet.interfaces import IConnector
from twisted.internet.protocol import Protocol
from twisted.python import log, usage
from twisted.python.failure import Failure

from . import decoders
from .const import Encoding, HextileEncoding, AuthTypes, MsgC2S, MsgS2C
from .keys import Key

Rect = Tuple[int, int, int, int]
Ver = Tuple[int, int]

# ~ from twisted.internet import reactor


@dataclass(frozen=True)
class PixelFormat:
    """:rfc:`6143` §7.4. Pixel Format Data Structure."""

    bpp: int = 32  # u8: bits-per-pixel
    depth: int = 24  # u8
    bigendian: bool = False  # u8
    truecolor: bool = True  # u8
    redmax: int = 255  # u16
    greenmax: int = 255  # u16
    bluemax: int = 255  # u16
    redshift: int = 0  # u8
    greenshift: int = 8  # u8
    blueshift: int = 16  # u8

    STRUCT: ClassVar = Struct("!BB??HHHBBBxxx")
    VALIDATE: ClassVar = False

    def __post_init__(self) -> None:
        if not self.VALIDATE:
            return
        assert self.bpp in {8, 16, 24, 32}, f"bpp={self.bpp}"
        assert 1 <= self.depth <= self.bpp, f"depth={self.depth} <= bpp={self.bpp}"
        if self.truecolor:
            for max, shift in zip(
                (self.redmax, self.greenmax, self.bluemax),
                (self.redshift, self.greenshift, self.blueshift),
            ):
                assert 1 <= max <= 0xFFFF, f"1 <= max={max} <= 0xffff"
                assert max & (max + 1) == 0, f"max={max} not a 2**n-1"
                assert (
                    0 <= shift <= self.bpp - max.bit_length()
                ), f"shift={shift} not in bpp={self.bpp}"

    @property
    def bypp(self) -> int:  # bytes-per-pixel
        return (7 + self.bpp) // 8

    @classmethod
    def from_bytes(cls, block: bytes) -> PixelFormat:
        return cls(*cls.STRUCT.unpack(block))

    def to_bytes(self) -> bytes:
        return cast(bytes, self.STRUCT.pack(*astuple(self)))


# ZRLE helpers
def _zrle_next_bit(it: Iterator[int], pixels_in_tile: int) -> Iterator[int]:
    num_pixels = 0
    while True:
        b = next(it)

        for n in range(8):
            value = b >> (7 - n)
            yield value & 1

            num_pixels += 1
            if num_pixels == pixels_in_tile:
                return


def _zrle_next_dibit(it: Iterator[int], pixels_in_tile: int) -> Iterator[int]:
    num_pixels = 0
    while True:
        b = next(it)

        for n in range(0, 8, 2):
            value = b >> (6 - n)
            yield value & 3

            num_pixels += 1
            if num_pixels == pixels_in_tile:
                return


def _zrle_next_nibble(it: Iterator[int], pixels_in_tile: int) -> Iterator[int]:
    num_pixels = 0
    while True:
        b = next(it)

        for n in range(0, 8, 4):
            value = b >> (4 - n)
            yield value & 15

            num_pixels += 1
            if num_pixels == pixels_in_tile:
                return


class RFBClient(Protocol):  # type: ignore[misc]
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
    SUPPORTED_AUTHS = {
        AuthTypes.NONE,
        AuthTypes.VNC_AUTHENTICATION,
        AuthTypes.DIFFIE_HELLMAN,
    }
    _UNMIGRATED_ENCODINGS = {
        Encoding.HEXTILE,
        Encoding.ZRLE,
        Encoding.PSEUDO_CURSOR,
        Encoding.PSEUDO_DESKTOP_SIZE,
        Encoding.PSEUDO_LAST_RECT,
        Encoding.PSEUDO_QEMU_EXTENDED_KEY_EVENT,
    }
    SUPPORTED_ENCODINGS = set(decoders.DECODERS) | _UNMIGRATED_ENCODINGS

    # Greater than any u16 dimension, so it refuses nothing until a subclass
    # narrows it.
    MAX_DESKTOP_SIZE = 0x10000

    _HEADER = b"RFB 000.000\n"
    _HEADER_TRANSLATE = bytes.maketrans(b"0123456789", b"0" * 10)

    _CHANGING_HOOKS = ("fillRectangle", "updateRectangle")

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for name in cls._CHANGING_HOOKS:
            if not getattr(cls, name).__module__.startswith("vncdotool."):
                warnings.warn(
                    f"{name} will change in a future release; please comment "
                    "on https://github.com/sibson/vncdotool/issues/385 if "
                    "you rely on it",
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
        self._zlib_stream = zlib.decompressobj(0)
        self.negotiated_encodings = {
            Encoding.RAW,
        }
        self.pixel_format = PixelFormat()
        self.width = 0
        self.height = 0
        self._rect_backing = bytearray()
        self._decoders = decoders.build()

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
            self.vncProtocolError(f"invalid initial server response {head!r}")
            self.transport.loseConnection()

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
            if sec_type == AuthTypes.NONE:
                if self._version < (3, 8):
                    self._doClientInitialization()
                else:
                    self.expect(self._handleVNCAuthResult, 4)
            elif sec_type == AuthTypes.VNC_AUTHENTICATION:
                self.expect(self._handleVNCAuth, 16)
            elif sec_type == AuthTypes.DIFFIE_HELLMAN:
                self.expect(self._handleDHAuth, 4)
        else:
            self.vncProtocolError(f"unknown security types: {types!r}")
            self.transport.loseConnection()

    def _handleAuth(self, block: bytes) -> None:
        (auth,) = unpack("!I", block)
        # ~ print(f"{auth=}")
        if auth == AuthTypes.INVALID:
            self.expect(self._handleConnFailed, 4)
        elif auth == AuthTypes.NONE:
            self._doClientInitialization()
        elif auth == AuthTypes.VNC_AUTHENTICATION:
            self.expect(self._handleVNCAuth, 16)
        else:
            self.vncProtocolError(f"unknown auth response {AuthTypes.lookup(auth)!r}")
            self.transport.loseConnection()

    def _handleConnFailed(self, block: bytes) -> None:
        (waitfor,) = unpack("!I", block)
        self.expect(self._handleConnMessage, waitfor)

    def _handleConnMessage(self, block: bytes) -> None:
        self.vncProtocolError(f"Connection refused: {block!r}")
        self.transport.loseConnection()

    def _handleVNCAuth(self, block: bytes) -> None:
        self._challenge = block
        self.vncRequestPassword()
        self.expect(self._handleVNCAuthResult, 4)

    def _handleDHAuth(self, block: bytes) -> None:
        self.generator, self.keyLen = unpack("!HH", block)
        self.expect(self._handleDHAuthKey, self.keyLen)

    def _handleDHAuthKey(self, block: bytes) -> None:
        self.modulus = block
        self.expect(self._handleDHAuthCert, self.keyLen)

    def _handleDHAuthCert(self, block: bytes) -> None:
        self.serverKey = block

        self.ardRequestCredentials()

        self._encryptArd()
        self.expect(self._handleVNCAuthResult, 4)

    def _encryptArd(self) -> None:
        userStruct = f"{self.factory.username:\0<64}{self.factory.password:\0<64}"

        p = int.from_bytes(self.modulus, "big")
        sk = int.from_bytes(self.serverKey, "big")
        with warnings.catch_warnings():
            # ARD auth is specified over classic finite-field DH; the server
            # picks p/g and there is no other algorithm to negotiate into.
            # Tracking upstream removal: https://github.com/sibson/vncdotool/issues/388
            warnings.simplefilter("ignore", CryptographyDeprecationWarning)
            param_nums = dh.DHParameterNumbers(p=p, g=self.generator)
            server_key = dh.DHPublicNumbers(sk, param_nums).public_key()

        params = param_nums.parameters()
        private_key = params.generate_private_key()
        shared_key = private_key.exchange(server_key)

        h = hashes.Hash(hashes.MD5())
        h.update(shared_key)
        key_digest = h.finalize()

        cipher = Cipher(algorithms.AES(key_digest), modes.ECB())
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(userStruct.encode("utf-8"))
        ciphertext += encryptor.finalize()

        public_key = private_key.public_key()
        y = public_key.public_numbers().y.to_bytes(self.keyLen, "big")

        self.transport.write(ciphertext + y)

    def ardRequestCredentials(self) -> None:
        if self.factory.username is None:
            self.factory.username = input("username: ")
        if self.factory.password is None:
            self.factory.password = getpass.getpass("password:")

    def sendPassword(self, password: str) -> None:
        """send password"""
        self.transport.write(des_encrypt(_vnc_des(password), self._challenge))

    def _handleVNCAuthResult(self, block: bytes) -> None:
        (result,) = unpack("!I", block)
        # ~ print(f"{auth=}")
        if result == 0:  # OK
            self._doClientInitialization()
            return
        elif result == 1:  # failed
            if self._version < (3, 8):
                self.vncAuthFailed("authentication failed")
                self.transport.loseConnection()
            else:
                self.expect(self._handleAuthFailed, 4)
        elif result == 2:  # too many
            if self._version < (3, 8):
                self.vncAuthFailed("too many tries to log in")
                self.transport.loseConnection()
            else:
                self.expect(self._handleAuthFailed, 4)
        else:
            log.msg(f"unknown auth response ({result})")
            self.transport.loseConnection()

    def _handleAuthFailed(self, block: bytes) -> None:
        (waitfor,) = unpack("!I", block)
        self.expect(self._handleAuthFailedMessage, waitfor)

    def _handleAuthFailedMessage(self, block: bytes) -> None:
        self.vncAuthFailed(block)
        self.transport.loseConnection()

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
        elif msgid == MsgS2C.SET_COLOUR_MAP_ENTRIES:
            self.expect(self._handleColourMapEntries, 5)
        elif msgid == MsgS2C.BELL:
            self.bell()
            self.expect(self._handleConnection, 1)
        elif msgid == MsgS2C.SERVER_CUT_TEXT:
            self.expect(self._handleServerCutText, 7)
        else:
            self.vncProtocolError(f"unknown message received {MsgS2C.lookup(msgid)!r}")
            self.transport.loseConnection()

    def _handleFramebufferUpdate(self, block: bytes) -> None:
        (self.rectangles,) = unpack("!xH", block)
        self.rectanglePos: list[Rect] = []
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
        log.msg(f"x={x} y={y} w={width} h={height} {Encoding.lookup(encoding)!r}")
        if encoding == Encoding.PSEUDO_LAST_RECT:
            self.rectangles = 0

        if self.rectangles:
            self.rectangles -= 1
            self.rectanglePos.append((x, y, width, height))
            decoder = self._decoders.get(encoding)
            if decoder is not None:
                self._decodeRectangle(decoder, x, y, width, height)
            elif encoding == Encoding.HEXTILE:
                self._doNextHextileSubrect(None, None, x, y, width, height, None, None)
            elif encoding == Encoding.ZRLE:
                self.expect(self._handleDecodeZRLE, 4, x, y, width, height)
            elif encoding == Encoding.PSEUDO_CURSOR:
                length = width * height * self.bypp
                length += ((width + 7) // 8) * height
                self.expect(self._handleDecodePsuedoCursor, length, x, y, width, height)
            elif encoding == Encoding.PSEUDO_DESKTOP_SIZE:
                del self.rectanglePos[-1]  # undo append as this carries no pixel data
                self._handleDecodeDesktopSize(width, height)
            elif encoding == Encoding.PSEUDO_QEMU_EXTENDED_KEY_EVENT:
                self.negotiated_encodings.add(Encoding.PSEUDO_QEMU_EXTENDED_KEY_EVENT)
                del self.rectanglePos[-1]  # undo append as this is no real update
                self._doConnection()
            else:
                self.vncProtocolError(
                    f"unknown encoding received {Encoding.lookup(encoding)!r}"
                )
                self.transport.loseConnection()
        else:
            self._doConnection()

    def _decodeRectangle(
        self, decoder: decoders.Decoder, x: int, y: int, width: int, height: int
    ) -> None:
        """Drive one decoder against `expect` until it stops."""
        rect = (x, y, width, height)
        if isinstance(decoder, decoders.ControlDecoder):
            decoder.applyToClient(self, rect)
            self._doConnection()
            return

        if isinstance(decoder, decoders.PixelDecoder):
            target = self._rectBuffer(width, height)
            if target is None:
                return
            self._pumpDecoder(
                None,
                decoder.decodePixels(target, self.pixel_format),
                (decoder, target, rect),
            )
        else:
            self._pumpDecoder(
                None, decoder.decodeForClient(self, rect, self.pixel_format), None
            )

    def _finishRectangle(
        self, decoder: decoders.PixelDecoder, target: decoders.RectBuffer, rect: Rect
    ) -> None:
        x, y, width, height = rect
        self.updateRectangle(
            x, y, width, height, target.tobytes(),
            decoder.output_format(self.pixel_format),
        )

    def _rectBuffer(self, width: int, height: int) -> decoders.RectBuffer | None:
        """A buffer for one rectangle, or None having failed the connection."""
        limit_w = self.width or self.MAX_DESKTOP_SIZE
        limit_h = self.height or self.MAX_DESKTOP_SIZE
        if not (0 <= width <= limit_w and 0 <= height <= limit_h):
            self.abortConnection(
                f"rectangle {width}x{height} does not fit a {limit_w}x{limit_h} framebuffer"
            )
            return None
        needed = width * height * self.bypp
        try:
            if len(self._rect_backing) < needed:
                self._rect_backing = bytearray(needed)
            return decoders.RectBuffer(width, height, self.bypp, self._rect_backing)
        except MemoryError:
            self.abortConnection(f"no memory for a {width}x{height} rectangle")
            return None

    def _pumpDecoder(
        self,
        block: bytes | None,
        generator: Iterator[int],
        finish: tuple[decoders.PixelDecoder, decoders.RectBuffer, Rect] | None,
    ) -> None:
        try:
            size = generator.send(block)
        except StopIteration:
            if finish is not None:
                self._finishRectangle(*finish)
            self._doConnection()
            return
        except (decoders.DecodeError, StructError, MemoryError, zlib.error) as exc:
            generator.close()
            self.abortConnection(f"cannot decode this rectangle: {exc}")
            return

        if size < 0:
            generator.close()
            self.abortConnection(f"decoder asked for {size} bytes")
            return
        self.expect(self._pumpDecoder, size, generator, finish)

    # ---  Hexile Encoding

    def _doNextHextileSubrect(
        self,
        bg: bytes | None,
        color: bytes | None,
        x: int,
        y: int,
        width: int,
        height: int,
        tx: int | None,
        ty: int | None,
    ) -> None:
        # ~ print("_doNextHextileSubrect %r" % ((color, x, y, width, height, tx, ty),))
        # coords of next tile
        # its line after line of tiles
        # finished when the last line is completly received

        # dont inc the first time
        if tx is not None:
            assert ty is not None
            # calc next subrect pos
            tx += 16
            if tx >= x + width:
                tx = x
                ty += 16
        else:
            tx = x
            ty = y
        # more tiles?
        if ty >= y + height:
            self._doConnection()
        else:
            self.expect(
                self._handleDecodeHextile, 1, bg, color, x, y, width, height, tx, ty
            )

    def _handleDecodeHextile(
        self,
        block: bytes,
        bg: bytes,
        color: bytes,
        x: int,
        y: int,
        width: int,
        height: int,
        tx: int,
        ty: int,
    ) -> None:
        subencoding = HextileEncoding(block[0])
        # calc tile size
        tw = th = 16
        if x + width - tx < 16:
            tw = x + width - tx
        if y + height - ty < 16:
            th = y + height - ty
        # decode tile
        if subencoding & HextileEncoding.RAW:
            self.expect(
                self._handleDecodeHextileRAW,
                tw * th * self.bypp,
                bg,
                color,
                x,
                y,
                width,
                height,
                tx,
                ty,
                tw,
                th,
            )
        else:
            numbytes = 0
            if subencoding & HextileEncoding.BACKGROUND_SPECIFIED:
                numbytes += self.bypp
            if subencoding & HextileEncoding.FOREGROUND_SPECIFIED:
                numbytes += self.bypp
            if subencoding & HextileEncoding.ANY_SUBRECTS:
                numbytes += 1
            if numbytes:
                self.expect(
                    self._handleDecodeHextileSubrect,
                    numbytes,
                    subencoding,
                    bg,
                    color,
                    x,
                    y,
                    width,
                    height,
                    tx,
                    ty,
                    tw,
                    th,
                )
            else:
                self.fillRectangle(tx, ty, tw, th, bg)
                self._doNextHextileSubrect(bg, color, x, y, width, height, tx, ty)

    def _handleDecodeHextileSubrect(
        self,
        block: bytes,
        subencoding: HextileEncoding,
        bg: bytes,
        color: bytes,
        x: int,
        y: int,
        width: int,
        height: int,
        tx: int,
        ty: int,
        tw: int,
        th: int,
    ) -> None:
        subrects = 0
        pos = 0
        if subencoding & HextileEncoding.BACKGROUND_SPECIFIED:
            bg = block[: self.bypp]
            pos += self.bypp
        self.fillRectangle(tx, ty, tw, th, bg)
        if subencoding & HextileEncoding.FOREGROUND_SPECIFIED:
            color = block[pos : pos + self.bypp]
            pos += self.bypp
        if subencoding & HextileEncoding.ANY_SUBRECTS:
            # ~ (subrects, ) = unpack("!B", block)
            subrects = block[pos]
        # ~ print(subrects)
        if subrects:
            if subencoding & HextileEncoding.SUBRECTS_COLORED:
                self.expect(
                    self._handleDecodeHextileSubrectsColoured,
                    (self.bypp + 2) * subrects,
                    bg,
                    color,
                    subrects,
                    x,
                    y,
                    width,
                    height,
                    tx,
                    ty,
                    tw,
                    th,
                )
            else:
                self.expect(
                    self._handleDecodeHextileSubrectsFG,
                    2 * subrects,
                    bg,
                    color,
                    subrects,
                    x,
                    y,
                    width,
                    height,
                    tx,
                    ty,
                    tw,
                    th,
                )
        else:
            self._doNextHextileSubrect(bg, color, x, y, width, height, tx, ty)

    def _handleDecodeHextileRAW(
        self,
        block: bytes,
        bg: bytes,
        color: bytes,
        x: int,
        y: int,
        width: int,
        height: int,
        tx: int,
        ty: int,
        tw: int,
        th: int,
    ) -> None:
        """the tile is in raw encoding"""
        self.updateRectangle(tx, ty, tw, th, block, self.pixel_format)
        self._doNextHextileSubrect(bg, color, x, y, width, height, tx, ty)

    def _handleDecodeHextileSubrectsColoured(
        self,
        block: bytes,
        bg: bytes | None,
        color: bytes | None,
        subrects: int,
        x: int,
        y: int,
        width: int,
        height: int,
        tx: int,
        ty: int,
        tw: int,
        th: int,
    ) -> None:
        """subrects with their own color"""
        sz = self.bypp + 2
        pos = 0
        end = len(block)
        while pos < end:
            pos2 = pos + self.bypp
            color = block[pos:pos2]
            xy = block[pos2]
            wh = block[pos2 + 1]
            sx = xy >> 4
            sy = xy & 0xF
            sw = (wh >> 4) + 1
            sh = (wh & 0xF) + 1
            self.fillRectangle(tx + sx, ty + sy, sw, sh, color)
            pos += sz
        self._doNextHextileSubrect(bg, color, x, y, width, height, tx, ty)

    def _handleDecodeHextileSubrectsFG(
        self,
        block: bytes,
        bg: bytes,
        color: bytes,
        subrects: int,
        x: int,
        y: int,
        width: int,
        height: int,
        tx: int,
        ty: int,
        tw: int,
        th: int,
    ) -> None:
        """all subrect with same color"""
        pos = 0
        end = len(block)
        while pos < end:
            xy = block[pos]
            wh = block[pos + 1]
            sx = xy >> 4
            sy = xy & 0xF
            sw = (wh >> 4) + 1
            sh = (wh & 0xF) + 1
            self.fillRectangle(tx + sx, ty + sy, sw, sh, color)
            pos += 2
        self._doNextHextileSubrect(bg, color, x, y, width, height, tx, ty)

    # ---  ZRLE Encoding
    def _handleDecodeZRLE(
        self,
        block: bytes,
        x: int,
        y: int,
        width: int,
        height: int,
    ) -> None:
        """
        Handle ZRLE encoding.
        See `ZRLW <https://tools.ietf.org/html/rfc6143#section-7.7.6>`_
        and `TRLE <https://tools.ietf.org/html/rfc6143#section-7.7.5>`_
        """
        (compressed_bytes,) = unpack("!L", block)
        self.expect(self._handleDecodeZRLEdata, compressed_bytes, x, y, width, height)

    def _handleDecodeZRLEdata(
        self,
        block: bytes,
        x: int,
        y: int,
        width: int,
        height: int,
    ) -> None:
        tx = x
        ty = y

        data = self._zlib_stream.decompress(block)
        it = iter(data)

        def cpixel(i: Iterator[int]) -> bytearray:
            return bytearray(
                (
                    next(i),
                    next(i),
                    next(i),
                    0xFF,
                )
            )

        for subencoding in it:
            # calc tile size
            tw = th = 64
            if x + width - tx < 64:
                tw = x + width - tx
            if y + height - ty < 64:
                th = y + height - ty

            pixels_in_tile = tw * th

            # decode next tile
            num_pixels = 0
            pixel_data = bytearray()
            palette_size = subencoding & 127
            if subencoding & 0x80:
                # RLE

                def do_rle(pixel: bytes) -> int:
                    run_length_next = next(it)
                    run_length = run_length_next
                    while run_length_next == 255:
                        run_length_next = next(it)
                        run_length += run_length_next
                    pixel_data.extend(pixel * (run_length + 1))
                    return run_length + 1

                if palette_size == 0:
                    # plain RLE
                    while num_pixels < pixels_in_tile:
                        color = cpixel(it)
                        num_pixels += do_rle(color)
                    if num_pixels != pixels_in_tile:
                        raise ValueError("too many pixels")
                else:
                    palette = [cpixel(it) for p in range(palette_size)]

                    while num_pixels < pixels_in_tile:
                        palette_index = next(it)
                        if palette_index & 0x80:
                            palette_index &= 0x7F
                            # run of length > 1, more bytes follow to determine run length
                            num_pixels += do_rle(palette[palette_index])
                        else:
                            # run of length 1
                            pixel_data.extend(palette[palette_index])
                            num_pixels += 1
                    if num_pixels != pixels_in_tile:
                        raise ValueError("too many pixels")

                self.updateRectangle(
                    tx, ty, tw, th, bytes(pixel_data), self.pixel_format
                )
            else:
                # No RLE
                if palette_size == 0:
                    # Raw pixel data
                    for _ in range(pixels_in_tile):
                        pixel_data.extend(cpixel(it))
                    self.updateRectangle(
                        tx, ty, tw, th, bytes(pixel_data), self.pixel_format
                    )
                elif palette_size == 1:
                    # Fill tile with plain color
                    color = cpixel(it)
                    self.fillRectangle(tx, ty, tw, th, bytes(color))
                elif palette_size > 16:
                    raise ValueError(f"Palette of size {palette_size} is not allowed")
                else:
                    palette = [cpixel(it) for _ in range(palette_size)]
                    if palette_size == 2:
                        next_index = _zrle_next_bit(it, pixels_in_tile)
                    elif palette_size == 3 or palette_size == 4:
                        next_index = _zrle_next_dibit(it, pixels_in_tile)
                    else:
                        next_index = _zrle_next_nibble(it, pixels_in_tile)

                    for palette_index in next_index:
                        pixel_data.extend(palette[palette_index])
                    self.updateRectangle(
                        tx, ty, tw, th, bytes(pixel_data), self.pixel_format
                    )

            # Next tile
            tx = tx + 64
            if tx >= x + width:
                tx = x
                ty = ty + 64

        self._doConnection()

    # --- Pseudo Cursor Encoding
    def _handleDecodePsuedoCursor(
        self, block: bytes, x: int, y: int, width: int, height: int
    ) -> None:
        split = width * height * self.bypp
        image = block[:split]
        mask = block[split:]
        self.updateCursor(x, y, width, height, image, mask)
        self._doConnection()

    # --- Pseudo Desktop Size Encoding
    def _handleDecodeDesktopSize(self, width: int, height: int) -> None:
        self.updateDesktopSize(width, height)
        self._doConnection()

    # ---  other server messages

    def _handleColourMapEntries(self, block: bytes) -> None:
        (first_color, number_of_colors) = unpack("!xHH", block)
        self.expect(
            self._handleColourMapEntriesValue, 6 * number_of_colors, first_color
        )

    def _handleColourMapEntriesValue(self, block: bytes, first_color: int) -> None:
        colors = [
            unpack_from("!HHH", block, offset) for offset in range(0, len(block), 6)
        ]
        self.set_color_map(first_color, cast(List[Tuple[int, int, int]], colors))
        self.expect(self._handleConnection, 1)

    def _handleServerCutText(self, block: bytes) -> None:
        (length,) = unpack("!xxxI", block)
        self.expect(self._handleServerCutTextValue, length)

    def _handleServerCutTextValue(self, block: bytes) -> None:
        self.copy_text(block.decode("iso-8859-1"))
        self.expect(self._handleConnection, 1)

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

    def commitUpdate(self, rectangles: list[Rect] | None = None) -> None:
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


class RFBFactory(protocol.ClientFactory):  # type: ignore[misc]
    """A factory for remote frame buffer connections."""

    # the class of the protocol to build
    # should be overriden by application to use a derrived class
    protocol = RFBClient

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
    # equivalent to single-DES
    encryptor = Cipher(algorithms.TripleDES(key * 3), modes.ECB()).encryptor()
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

    class RFBTestFactory(protocol.ClientFactory):  # type: ignore[misc]
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

    class Options(usage.Options):  # type: ignore[misc]
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
