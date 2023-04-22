"""
RFB protocol implementattion, client side.

Override RFBClient and RFBFactory in your application.
See vncviewer.py for an example.

Reference:
http://www.realvnc.com/docs/rfbproto.pdf

(C) 2003 cliechti@gmx.net

MIT License
"""

import getpass
import os
import sys
import zlib
from dataclasses import astuple, dataclass
from enum import IntEnum, IntFlag
from struct import Struct, pack, unpack, unpack_from
from typing import (
    Any,
    Callable,
    ClassVar,
    Collection,
    Dict,
    Iterator,
    List,
    Optional,
    Tuple,
    cast,
)

from Cryptodome.Cipher import AES, DES
from Cryptodome.Hash import MD5
from Cryptodome.Util.number import bytes_to_long, long_to_bytes
from twisted.application import internet, service
from twisted.internet import protocol
from twisted.internet.interfaces import IConnector
from twisted.internet.protocol import Protocol
from twisted.python import log, usage
from twisted.python.failure import Failure

Rect = Tuple[int, int, int, int]
Ver = Tuple[int, int]

# ~ from twisted.internet import reactor


class IntEnumLookup(IntEnum):
    @classmethod
    def lookup(cls, value: int) -> object:
        return cls._value2member_map_.get(value, f"<{cls.__name__}.UNKNOWN: {value:x}>")


class Encoding(IntEnumLookup):
    """encoding-type for SetEncodings()"""

    @staticmethod
    def s32(value: int) -> int:
        return value - 0x1_0000_0000 if value >= 0x8000_0000 else value

    def __new__(cls, value: int) -> "Encoding":
        return int.__new__(cls, cls.s32(value))

    @classmethod
    def lookup(cls, value: int) -> object:
        return super().lookup(cls.s32(value))

    RAW = 0
    COPY_RECTANGLE = 1
    RRE = 2
    CORRE = 4
    HEXTILE = 5
    ZLIB = 6
    TIGHT = 7
    ZLIBHEX = 8
    ULTRA = 9
    ULTRA2 = 10
    TRLE = 15
    ZRLE = 16
    HITACHI_ZYWRLE = 17
    H264 = 20
    JPEG = 21
    JRLE = 22
    OPEN_H264 = 50
    APPLE_1000 = 1000
    APPLE_1001 = 1001
    APPLE_1002 = 1002
    APPLE_1011 = 1011
    REAL_1024 = 1024  # ... 1099
    APPLE_1100 = 1100
    APPLE_1101 = 1101
    APPLE_1102 = 1102
    APPLE_1103 = 1103
    APPLE_1104 = 1104
    APPLE_1105 = 1105
    TIGHT_1 = -1  # ... -22
    JPEG_23 = -23
    JPEG_24 = -24
    JPEG_25 = -25
    JPEG_26 = -26
    JPEG_27 = -27
    JPEG_28 = -28
    JPEG_29 = -29
    JPEG_30 = -30
    JPEG_31 = -31
    JPEG_32 = -32
    TIGHT_33 = -33  # ... -218
    LIBVNCSERVER_219 = -219  # historical
    LIBVNCSERVER_220 = -220  # historical
    LIBVNCSERVER_221 = -221  # historical
    LIBVNCSERVER_222 = -222  # historical
    PSEUDO_DESKTOP_SIZE = -223
    PSEUDO_LAST_RECT = -224
    POINTER_POS = -225
    TIGHT_226 = -226  # ... -238
    PSEUDO_CURSOR = -239
    PSEUDO_X_CURSOR = -240
    TIGHT_241 = -241  # ... -246
    PSEUDO_COMPRESSION_LEVEL_247 = -247
    PSEUDO_COMPRESSION_LEVEL_248 = -248
    PSEUDO_COMPRESSION_LEVEL_249 = -249
    PSEUDO_COMPRESSION_LEVEL_250 = -250
    PSEUDO_COMPRESSION_LEVEL_251 = -251
    PSEUDO_COMPRESSION_LEVEL_252 = -252
    PSEUDO_COMPRESSION_LEVEL_253 = -253
    PSEUDO_COMPRESSION_LEVEL_254 = -254
    PSEUDO_COMPRESSION_LEVEL_255 = -255
    PSEUDO_COMPRESSION_LEVEL_256 = -256
    PSEUDO_QEMU_POINTER_MODTION_CHANGE = -257
    PSEUDO_QEMU_EXTENDED_KEY_EVENT = -258
    PSEUDO_QEMU_AUDIO = -259
    TIGHT_PNG = -260
    PSEUDO_QEMU_LED_STATE = -261
    QEMU_262 = -262  # ...-272
    VMWARE_273 = -273  # ... -304
    PSEUDO_GII = -305
    POPA = -306
    PSEUDO_DESKTOP_NAME = -307
    PSEUDO_EXTENDED_DESKTOP_SIZE = -308
    PSEUDO_XVO = -309
    OLIVE_CALL_CONTROL = -310
    CLIENT_REDIRECT = -311
    PSEUDO_FENCE = -312
    PSEUDO_CONTINUOUS_UPDATES = -313
    PSEUDO_CURSOR_WITH_ALPHA = -314
    PSEUDO_JPEG_FINE_GRAINED_QUALITY_LEVEL = -412  # ... -512
    CAR_CONNECTIVITY_523 = -523  # ... -528
    PSEUDO_JPEG_SUBSAMLING_LEVEL = -763  # ... -768
    VA_H264 = 0x48323634
    VMWARE_0X574D5600 = 0x574D5600  # ... 0x574d56ff
    PSEUDO_VMWARE_CURSOR = 0x574D5664
    PSEUDO_VMWARE_CURSOR_STATE = 0x574D5665
    PSEUDO_VMWARE_CURSOR_POSITION = 0x574D5666
    PSEUDO_VMWARE_KEY_REPEAT = 0x574D5667
    PSEUDO_VMWARE_LED_STATE = 0x574D5668
    PSEUDO_VMWARE_DISPLAY_MODE_CHANGE = 0x574D5669
    PSEUDO_VMWARE_VIRTUAL_MACHINE_STATE = 0x574D566A
    PSEUDO_EXTENDED_CLIPBOARD = 0xC0A1E5CE
    PLUGIN_STREAMING = 0xC0A1E5CF
    KEYBOARD_LED_STATE = 0xFFFE0000
    SUPPORTED_MESSAGES = 0xFFFE0001
    SUPPORTED_ENCODINGS = 0xFFFE0002
    SERVER_IDENTITY = 0xFFFE0003
    LIBVNCSERVER_0XFFFE0004 = 0xFFFE0004  # ... 0xfffe00ff
    CACHE = 0xFFFF0000
    CACHE_ENABLE = 0xFFFF0001
    XOR_ZLIB = 0xFFFF0002
    XOR_MONO_RECT_ZLIB = 0xFFFF0003
    XOR_MULTI_COLOR_ZLIB = 0xFFFF0004
    SOLID_COLOR = 0xFFFF0005
    XOR_ENABLE = 0xFFFF0006
    CACHE_ZIP = 0xFFFF0007
    SOL_MONO_ZIP = 0xFFFF0008
    ULTRA_ZIP = 0xFFFF0009
    SERVER_STATE = 0xFFFF8000
    ENABLE_KEEP_ALIVE = 0xFFFF8001
    FTP_PROTOCOl_VERSION = 0xFFFF8002
    SESSION = 0xFFFF8003


class HextileEncoding(IntFlag):
    """RFC 6153 §7.7.4. Hextile Encoding."""

    RAW = 1
    BACKGROUND_SPECIFIED = 2
    FOREGROUND_SPECIFIED = 4
    ANY_SUBRECTS = 8
    SUBRECTS_COLORED = 16


class AuthTypes(IntEnumLookup):
    """RFC 6143 §7.1.2. Security Handshake."""

    INVALID = 0
    NONE = 1
    VNC_AUTHENTICATION = 2
    REALVNC_3 = 3
    REALVNC_4 = 4
    RSA_AES = 5
    RSA_AES_UNENCRYPTED = 6
    REALVNC_7 = 7
    REALVNC_8 = 8
    REALVNC_9 = 9
    REALVNC_10 = 10
    REALVNC_11 = 11
    REALVNC_12 = 12
    RSA_AES_2STEP = 13
    REALVNC_14 = 14
    REALVNC_15 = 15
    TIGHT = 16
    ULTRA = 17
    TLS = 18
    VENCRYPT = 19
    SASL = 20
    MD5 = 21
    XVP = 22
    SECURE_TUNNEL = 23
    INTEGRATED_SSH = 24
    DIFFIE_HELLMAN = 30
    APPLE_31 = 31
    APPLE_32 = 32
    APPLE_33 = 33
    APPLE_34 = 34
    APPLE_35 = 35
    MSLOGON2 = 113
    REALVNC_128 = 128
    RSA_AES256 = 129
    RSA_AES256_UNENCRYPTED = 130
    REALVNC_131 = 131
    REALVNC_132 = 132
    RSA_AES256_2STEP = 133
    REALVNC_134 = 134
    REALVNC_192 = 192


class MsgS2C(IntEnumLookup):
    """RFC 6143 §7.6. Server-to-Client Messages."""

    FRAMEBUFFER_UPDATE = 0
    SET_COLOUR_MAP_ENTRIES = 1
    BELL = 2
    SERVER_CUT_TEXT = 3
    RESIZE_FRAME_BUFFER_4 = 4
    KEY_FRAME_UPDATE = 5
    ULTRA_6 = 6
    FILE_TRANSFER = 7
    ULTRA_8 = 8
    ULTRA_9 = 9
    ULTRA_10 = 10
    TEXT_CHAT = 11
    ULTRA_12 = 12
    KEEP_ALIVE = 13
    ULTRA_14 = 14
    RESIZE_FRAME_BUFFER_15 = 15
    VMWARE_127 = 127
    CAR_CONNECTIVITY = 128
    END_OF_CONTINUOUS_UPDATES = 150
    SERVER_STATE = 173
    SERVER_FENCE = 248
    OLIVE_CALL_CONTROL = 249
    XVP_SERVER_MESSAGE = 250
    TIGHT = 252
    GII_SERVER_MESSAGE = 253  # General Input Interface
    VMWARE_254 = 254
    QEMU_SERVER_MESSAGE = 255


# keycodes
# for KeyEvent()
KEY_BackSpace = 0xFF08
KEY_Tab = 0xFF09
KEY_Return = 0xFF0D
KEY_Escape = 0xFF1B
KEY_Insert = 0xFF63
KEY_Delete = 0xFFFF
KEY_Home = 0xFF50
KEY_End = 0xFF57
KEY_PageUp = 0xFF55
KEY_PageDown = 0xFF56
KEY_Left = 0xFF51
KEY_Up = 0xFF52
KEY_Right = 0xFF53
KEY_Down = 0xFF54
KEY_F1 = 0xFFBE
KEY_F2 = 0xFFBF
KEY_F3 = 0xFFC0
KEY_F4 = 0xFFC1
KEY_F5 = 0xFFC2
KEY_F6 = 0xFFC3
KEY_F7 = 0xFFC4
KEY_F8 = 0xFFC5
KEY_F9 = 0xFFC6
KEY_F10 = 0xFFC7
KEY_F11 = 0xFFC8
KEY_F12 = 0xFFC9
KEY_F13 = 0xFFCA
KEY_F14 = 0xFFCB
KEY_F15 = 0xFFCC
KEY_F16 = 0xFFCD
KEY_F17 = 0xFFCE
KEY_F18 = 0xFFCF
KEY_F19 = 0xFFD0
KEY_F20 = 0xFFD1
KEY_ShiftLeft = 0xFFE1
KEY_ShiftRight = 0xFFE2
KEY_ControlLeft = 0xFFE3
KEY_ControlRight = 0xFFE4
KEY_MetaLeft = 0xFFE7
KEY_MetaRight = 0xFFE8
KEY_AltLeft = 0xFFE9
KEY_AltRight = 0xFFEA

KEY_Scroll_Lock = 0xFF14
KEY_Sys_Req = 0xFF15
KEY_Num_Lock = 0xFF7F
KEY_Caps_Lock = 0xFFE5
KEY_Pause = 0xFF13
KEY_Super_L = 0xFFEB  # windows-key, apple command key
KEY_Super_R = 0xFFEC  # windows-key, apple command key
KEY_Hyper_L = 0xFFED
KEY_Hyper_R = 0xFFEE

KEY_KP_0 = 0xFFB0
KEY_KP_1 = 0xFFB1
KEY_KP_2 = 0xFFB2
KEY_KP_3 = 0xFFB3
KEY_KP_4 = 0xFFB4
KEY_KP_5 = 0xFFB5
KEY_KP_6 = 0xFFB6
KEY_KP_7 = 0xFFB7
KEY_KP_8 = 0xFFB8
KEY_KP_9 = 0xFFB9
KEY_KP_Enter = 0xFF8D

KEY_ForwardSlash = 0x002F
KEY_BackSlash = 0x005C
KEY_SpaceBar = 0x0020


@dataclass(frozen=True)
class PixelFormat:
    """RFC 6143 §7.4. Pixel Format Data Structure"""

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
    def from_bytes(cls, block: bytes) -> "PixelFormat":
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
    SUPPORTED_ENCODINGS = {
        Encoding.RAW,
        Encoding.COPY_RECTANGLE,
        Encoding.RRE,
        Encoding.CORRE,
        Encoding.HEXTILE,
        Encoding.ZRLE,
        Encoding.PSEUDO_CURSOR,
        Encoding.PSEUDO_DESKTOP_SIZE,
        Encoding.PSEUDO_LAST_RECT,
        Encoding.PSEUDO_QEMU_EXTENDED_KEY_EVENT,
    }

    _HEADER = b"RFB 000.000\n"
    _HEADER_TRANSLATE = bytes.maketrans(b"0123456789", b"0" * 10)

    def __init__(self) -> None:
        self._packet = bytearray()
        self._handler = self._handleInitial
        self._expected_len = 12
        self._expected_args: Tuple[Any, ...] = ()
        self._expected_kwargs: Dict[str, Any] = {}
        self._already_expecting = False
        self._version: Ver = (0, 0)
        self._version_server: Ver = (0, 0)
        self._zlib_stream = zlib.decompressobj(0)
        self.negotiated_encodings = {
            Encoding.RAW,
        }
        self.pixel_format = PixelFormat()

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
            log.msg(f"invalid initial server response {head!r}")
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
            log.msg(f"unknown security types: {types!r}")
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
            log.msg(f"unknown auth response {AuthTypes.lookup(auth)!r}")
            self.transport.loseConnection()

    def _handleConnFailed(self, block: bytes) -> None:
        (waitfor,) = unpack("!I", block)
        self.expect(self._handleConnMessage, waitfor)

    def _handleConnMessage(self, block: bytes) -> None:
        log.msg(f"Connection refused: {block!r}")
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

        s = bytes_to_long(os.urandom(512))
        g = self.generator
        m = bytes_to_long(self.modulus)
        sk = bytes_to_long(self.serverKey)

        key = long_to_bytes(pow(g, s, m))
        shared = long_to_bytes(pow(sk, s, m))

        h = MD5.new()
        h.update(shared)
        keyDigest = h.digest()

        cipher = AES.new(keyDigest, AES.MODE_ECB)
        ciphertext = cipher.encrypt(userStruct.encode("utf-8"))
        self.transport.write(ciphertext + key)

    def ardRequestCredentials(self) -> None:
        if self.factory.username is None:
            self.factory.username = input("username: ")
        if self.factory.password is None:
            self.factory.password = getpass.getpass("password:")

    def sendPassword(self, password: str) -> None:
        """send password"""
        key = _vnc_des(password)
        des = DES.new(key, DES.MODE_ECB)
        response = des.encrypt(self._challenge)
        self.transport.write(response)

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
            log.msg(f"unknown message received {MsgS2C.lookup(msgid)!r}")
            self.transport.loseConnection()

    def _handleFramebufferUpdate(self, block: bytes) -> None:
        (self.rectangles,) = unpack("!xH", block)
        self.rectanglePos: List[Rect] = []
        self.beginUpdate()
        self._doConnection()

    def _doConnection(self) -> None:
        if self.rectangles:
            self.expect(self._handleRectangle, 12)
        else:
            if self.rectanglePos:
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
            if encoding == Encoding.COPY_RECTANGLE:
                self.expect(self._handleDecodeCopyrect, 4, x, y, width, height)
            elif encoding == Encoding.RAW:
                self.expect(
                    self._handleDecodeRAW,
                    width * height * self.bypp,
                    x,
                    y,
                    width,
                    height,
                )
            elif encoding == Encoding.HEXTILE:
                self._doNextHextileSubrect(None, None, x, y, width, height, None, None)
            elif encoding == Encoding.CORRE:
                self.expect(self._handleDecodeCORRE, 4 + self.bypp, x, y, width, height)
            elif encoding == Encoding.RRE:
                self.expect(self._handleDecodeRRE, 4 + self.bypp, x, y, width, height)
            elif encoding == Encoding.ZRLE:
                self.expect(self._handleDecodeZRLE, 4, x, y, width, height)
            elif encoding == Encoding.PSEUDO_CURSOR:
                length = width * height * self.bypp
                length += ((width + 7) // 8) * height
                self.expect(self._handleDecodePsuedoCursor, length, x, y, width, height)
            elif encoding == Encoding.PSEUDO_DESKTOP_SIZE:
                self._handleDecodeDesktopSize(width, height)
            elif encoding == Encoding.PSEUDO_QEMU_EXTENDED_KEY_EVENT:
                self.negotiated_encodings.add(Encoding.PSEUDO_QEMU_EXTENDED_KEY_EVENT)
                del self.rectanglePos[-1]  # undo append as this is no real update
                self._doConnection()
            else:
                log.msg(f"unknown encoding received {Encoding.lookup(encoding)!r}")
                self.transport.loseConnection()
        else:
            self._doConnection()

    # ---  RAW Encoding

    def _handleDecodeRAW(
        self, block: bytes, x: int, y: int, width: int, height: int
    ) -> None:
        # TODO convert pixel format?
        self.updateRectangle(x, y, width, height, block)
        self._doConnection()

    # ---  CopyRect Encoding

    def _handleDecodeCopyrect(
        self, block: bytes, x: int, y: int, width: int, height: int
    ) -> None:
        (srcx, srcy) = unpack("!HH", block)
        self.copyRectangle(srcx, srcy, x, y, width, height)
        self._doConnection()

    # ---  RRE Encoding

    def _handleDecodeRRE(
        self, block: bytes, x: int, y: int, width: int, height: int
    ) -> None:
        (subrects,) = unpack("!I", block[:4])
        color = block[4:]
        self.fillRectangle(x, y, width, height, color)
        if subrects:
            self.expect(self._handleRRESubRectangles, (8 + self.bypp) * subrects, x, y)
        else:
            self._doConnection()

    def _handleRRESubRectangles(self, block: bytes, topx: int, topy: int) -> None:
        # ~ print("_handleRRESubRectangle")
        pos = 0
        end = len(block)
        sz = self.bypp + 8
        format = f"!{self.bypp}sHHHH"
        while pos < end:
            (color, x, y, width, height) = unpack(format, block[pos : pos + sz])
            self.fillRectangle(topx + x, topy + y, width, height, color)
            pos += sz
        self._doConnection()

    # ---  CoRRE Encoding

    def _handleDecodeCORRE(
        self, block: bytes, x: int, y: int, width: int, height: int
    ) -> None:
        (subrects,) = unpack("!I", block[:4])
        color = block[4:]
        self.fillRectangle(x, y, width, height, color)
        if subrects:
            self.expect(
                self._handleDecodeCORRERectangles, (4 + self.bypp) * subrects, x, y
            )
        else:
            self._doConnection()

    def _handleDecodeCORRERectangles(self, block: bytes, topx: int, topy: int) -> None:
        # ~ print("_handleDecodeCORRERectangle")
        pos = 0
        sz = self.bypp + 4
        format = "!{self.bypp}sBBBB"
        while pos < sz:
            (color, x, y, width, height) = unpack(format, block[pos : pos + sz])
            self.fillRectangle(topx + x, topy + y, width, height, color)
            pos += sz
        self._doConnection()

    # ---  Hexile Encoding

    def _doNextHextileSubrect(
        self,
        bg: Optional[bytes],
        color: Optional[bytes],
        x: int,
        y: int,
        width: int,
        height: int,
        tx: Optional[int],
        ty: Optional[int],
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
        self.updateRectangle(tx, ty, tw, th, block)
        self._doNextHextileSubrect(bg, color, x, y, width, height, tx, ty)

    def _handleDecodeHextileSubrectsColoured(
        self,
        block: bytes,
        bg: Optional[bytes],
        color: Optional[bytes],
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
        See https://tools.ietf.org/html/rfc6143#section-7.7.6 (ZRLE)
        and https://tools.ietf.org/html/rfc6143#section-7.7.5 (TRLE)
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

                self.updateRectangle(tx, ty, tw, th, bytes(pixel_data))
            else:
                # No RLE
                if palette_size == 0:
                    # Raw pixel data
                    for _ in range(pixels_in_tile):
                        pixel_data.extend(cpixel(it))
                    self.updateRectangle(tx, ty, tw, th, bytes(pixel_data))
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
                    self.updateRectangle(tx, ty, tw, th, bytes(pixel_data))

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
        # ~ sys.stdout.write(repr(data) + '\n')
        # ~ print(f"{len(data), {len(self._packet)}")
        self._packet.extend(data)
        self._handler()

    def _handleExpected(self) -> None:
        if len(self._packet) >= self._expected_len:
            while len(self._packet) >= self._expected_len:
                self._already_expecting = True
                block = bytes(self._packet[: self._expected_len])
                del self._packet[: self._expected_len]
                # ~ log.msg(f"handle {block!r} with {self._expected_handler.__name__!r}")
                self._expected_handler(
                    block, *self._expected_args, **self._expected_kwargs
                )
            self._already_expecting = False

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
        pixformat = pixel_format.to_bytes()
        self.transport.write(pack("!Bxxx16s", 0, pixformat))
        self.pixel_format = pixel_format

    def setEncodings(self, list_of_encodings: Collection[Encoding]) -> None:
        self.transport.write(pack("!BxH", 2, len(list_of_encodings)))
        for encoding in list_of_encodings:
            log.msg(f"Offering {encoding!r}")
            self.transport.write(pack("!i", encoding))

    def framebufferUpdateRequest(
        self,
        x: int = 0,
        y: int = 0,
        width: Optional[int] = None,
        height: Optional[int] = None,
        incremental: bool = False,
    ) -> None:
        if width is None:
            width = self.width - x
        if height is None:
            height = self.height - y
        self.transport.write(pack("!BBHHHH", 3, incremental, x, y, width, height))

    def keyEvent(self, key: int, down: bool = True) -> None:
        """For most ordinary keys, the "keysym" is the same as the corresponding ASCII value.
        Other common keys are shown in the KEY_ constants."""
        self.transport.write(pack("!BBxxI", 4, down, key))

    def pointerEvent(self, x: int, y: int, buttonmask: int = 0) -> None:
        """Indicates either pointer movement or a pointer button press or release. The pointer is
        now at (x-position, y-position), and the current state of buttons 1 to 8 are represented
        by bits 0 to 7 of button-mask respectively, 0 meaning up, 1 meaning down (pressed).
        """
        self.transport.write(pack("!BBHH", 5, buttonmask, x, y))

    def clientCutText(self, message: str) -> None:
        """The client has new ISO 8859-1 (Latin-1) text in its cut buffer.
        (aka clipboard)
        """
        data = message.encode("iso-8859-1")
        self.transport.write(pack("!BxxxI", 6, len(data)) + data)

    # ------------------------------------------------------
    # callbacks
    # override these in your application
    # ------------------------------------------------------
    def vncConnectionMade(self) -> None:
        """connection is initialized and ready.
        typicaly, the pixel format is set here."""

    def vncRequestPassword(self) -> None:
        """a password is needed to log on, use sendPassword() to
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

    def beginUpdate(self) -> None:
        """called before a series of updateRectangle(),
        copyRectangle() or fillRectangle()."""

    def commitUpdate(self, rectangles: Optional[List[Rect]] = None) -> None:
        """called after a series of updateRectangle(), copyRectangle()
        or fillRectangle() are finished.
        typicaly, here is the place to request the next screen
        update with FramebufferUpdateRequest(incremental=1).
        argument is a list of tuples (x,y,w,h) with the updated
        rectangles."""

    def updateRectangle(
        self, x: int, y: int, width: int, height: int, data: bytes
    ) -> None:
        """new bitmap data. data is a string in the pixel format set
        up earlier."""

    def copyRectangle(
        self, srcx: int, srcy: int, x: int, y: int, width: int, height: int
    ) -> None:
        """used for copyrect encoding. copy the given rectangle
        (src, srxy, width, height) to the target coords (x,y)"""

    def fillRectangle(
        self, x: int, y: int, width: int, height: int, color: bytes
    ) -> None:
        """fill the area with the color. the color is a string in
        the pixel format set up earlier"""
        # fallback variant, use update recatngle
        # override with specialized function for better performance
        self.updateRectangle(x, y, width, height, color * width * height)

    def updateCursor(
        self, x: int, y: int, width: int, height: int, image: bytes, mask: bytes
    ) -> None:
        """New cursor, focuses at (x, y)"""

    def updateDesktopSize(self, width: int, height: int) -> None:
        """New desktop size of width*height."""

    def set_color_map(self, first: int, colors: List[Tuple[int, int, int]]) -> None:
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

    def __init__(self, password: Optional[str] = None, shared: bool = False) -> None:
        self.password = password
        self.shared = shared


def _vnc_des(password: str) -> bytes:
    """RFB protocol for authentication requires client to encrypt
    challenge sent by server with password using DES method. However,
    bits in each byte of the password are put in reverse order before
    using it as encryption key."""
    pw = f"{password:\0<8.8}"  # make sure its 8 chars long, zero padded
    key = pw.encode(
        "ASCII"
    )  # unspecified https://www.rfc-editor.org/rfc/rfc6143#section-7.2.2
    key = bytes(sum((128 >> i) if (k & (1 << i)) else 0 for i in range(8)) for k in key)
    return key


# --- test code only, see vncviewer.py

if __name__ == "__main__":

    class RFBTest(RFBClient):
        """dummy client"""

        def vncConnectionMade(self) -> None:
            print(f"Screen format: {self.pixel_format}")
            print(f"Desktop name: {self.name!r}")
            self.SetEncodings([Encoding.RAW])
            self.FramebufferUpdateRequest()

        def updateRectangle(
            self, x: int, y: int, width: int, height: int, data: bytes
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
