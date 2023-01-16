"""
RFB protocol implementattion, client side.

Override RFBClient and RFBFactory in your application.
See vncviewer.py for an example.

Reference:
http://www.realvnc.com/docs/rfbproto.pdf

(C) 2003 cliechti@gmx.net

MIT License
"""
# flake8: noqa

import getpass
import math
import os
import re
import sys
import zlib
from enum import IntEnum
from struct import pack, unpack
from typing import Any, Callable, Collection, Iterator, List, Optional, Tuple, TypeVar

from Crypto.Cipher import AES
from Crypto.Hash import MD5
from Crypto.Util.number import bytes_to_long, long_to_bytes
from Crypto.Util.Padding import pad
from twisted.application import internet, service
from twisted.internet import protocol
from twisted.internet.interfaces import IConnector
from twisted.internet.protocol import Protocol
from twisted.python import log, usage
from twisted.python.failure import Failure

from . import pyDes

Rect = Tuple[int, int, int, int]
Ver = Tuple[int, int]

#~ from twisted.internet import reactor

class Encoding(IntEnum):
    """encoding-type for SetEncodings()"""
    RAW = 0
    COPY_RECTANGLE = 1
    RRE = 2
    CORRE = 4
    HEXTILE = 5
    ZLIB = 6
    TIGHT = 7
    ZLIBHEX = 8
    ZRLE = 16
    #0xffffff00 to 0xffffffff tight options
    PSEUDO_DESKTOP_SIZE =  -223
    PSEUDO_CURSOR = -239


#keycodes
#for KeyEvent()
KEY_BackSpace = 0xff08
KEY_Tab =       0xff09
KEY_Return =    0xff0d
KEY_Escape =    0xff1b
KEY_Insert =    0xff63
KEY_Delete =    0xffff
KEY_Home =      0xff50
KEY_End =       0xff57
KEY_PageUp =    0xff55
KEY_PageDown =  0xff56
KEY_Left =      0xff51
KEY_Up =        0xff52
KEY_Right =     0xff53
KEY_Down =      0xff54
KEY_F1 =        0xffbe
KEY_F2 =        0xffbf
KEY_F3 =        0xffc0
KEY_F4 =        0xffc1
KEY_F5 =        0xffc2
KEY_F6 =        0xffc3
KEY_F7 =        0xffc4
KEY_F8 =        0xffc5
KEY_F9 =        0xffc6
KEY_F10 =       0xffc7
KEY_F11 =       0xffc8
KEY_F12 =       0xffc9
KEY_F13 =       0xFFCA
KEY_F14 =       0xFFCB
KEY_F15 =       0xFFCC
KEY_F16 =       0xFFCD
KEY_F17 =       0xFFCE
KEY_F18 =       0xFFCF
KEY_F19 =       0xFFD0
KEY_F20 =       0xFFD1
KEY_ShiftLeft = 0xffe1
KEY_ShiftRight = 0xffe2
KEY_ControlLeft = 0xffe3
KEY_ControlRight = 0xffe4
KEY_MetaLeft =  0xffe7
KEY_MetaRight = 0xffe8
KEY_AltLeft =   0xffe9
KEY_AltRight =  0xffea

KEY_Scroll_Lock = 0xFF14
KEY_Sys_Req =   0xFF15
KEY_Num_Lock =  0xFF7F
KEY_Caps_Lock = 0xFFE5
KEY_Pause =     0xFF13
KEY_Super_L =   0xFFEB  # windows-key, apple command key
KEY_Super_R =   0xFFEC  # windows-key, apple command key
KEY_Hyper_L =   0xFFED
KEY_Hyper_R =   0xFFEE

KEY_KP_0 =      0xFFB0
KEY_KP_1 =      0xFFB1
KEY_KP_2 =      0xFFB2
KEY_KP_3 =      0xFFB3
KEY_KP_4 =      0xFFB4
KEY_KP_5 =      0xFFB5
KEY_KP_6 =      0xFFB6
KEY_KP_7 =      0xFFB7
KEY_KP_8 =      0xFFB8
KEY_KP_9 =      0xFFB9
KEY_KP_Enter =  0xFF8D

KEY_ForwardSlash = 0x002F
KEY_BackSlash = 0x005C
KEY_SpaceBar=   0x0020


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

    RE_HANDSHAKE = re.compile(b"^RFB[ ]([0-9]{3})[.]([0-9]{3})[\n]")
    # https://www.rfc-editor.org/rfc/rfc6143#section-7.1.1
    SUPPORTED_VERSIONS = {
        (3, 3),
        # (3, 5),
        (3, 7),
        (3, 8),
        (3, 889),  # Apple Remote Desktop
    }
    SUPPORTED_TYPES = {
        1,
        2,  # VNC Auth
        30,  # Diffie-Hellman
    }

    def __init__(self) -> None:
        self._packet = bytearray()
        self._handler = self._handleInitial
        self._already_expecting = False
        self._version: Ver = (0, 0)
        self._version_server: Ver = (0, 0)
        self._zlib_stream = zlib.decompressobj(0)

    #------------------------------------------------------
    # states used on connection startup
    #------------------------------------------------------

    def _handleInitial(self) -> None:
        m = self.RE_HANDSHAKE.match(self._packet)
        if m:
            version_server = (int(m[1]), int(m[2]))
            if version_server == (3, 889): # Apple Remote Desktop
                version_server = (3, 8)
            if version_server in self.SUPPORTED_VERSIONS:
                version = version_server
            else:
                log.msg("Protocol version %d.%d not supported" % version_server)
                version = max(x for x in self.SUPPORTED_VERSIONS if x <= version_server)

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

    def _handleNumberSecurityTypes(self, block: bytes) -> None:
        (num_types,) = unpack("!B", block)
        if num_types:
            self.expect(self._handleSecurityTypes, num_types)
        else:
            self.expect(self._handleConnFailed, 4)

    def _handleSecurityTypes(self, block: bytes) -> None:
        types = unpack(f"!{len(block)}B", block)
        valid_types = set(types) & self.SUPPORTED_TYPES
        if valid_types:
            sec_type = max(valid_types)
            self.transport.write(pack("!B", sec_type))
            if sec_type == 1:
                if self._version < (3, 8):
                    self._doClientInitialization()
                else:
                    self.expect(self._handleVNCAuthResult, 4)
            elif sec_type == 2:
                self.expect(self._handleVNCAuth, 16)
            elif sec_type == 30:
                self.expect(self._handleDHAuth, 4)
        else:
            log.msg(f"unknown security types: {types!r}")

    def _handleAuth(self, block: bytes) -> None:
        (auth,) = unpack("!I", block)
        #~ print(f"{auth=}")
        if auth == 0:
            self.expect(self._handleConnFailed, 4)
        elif auth == 1:
            self._doClientInitialization()
            return
        elif auth == 2:
            self.expect(self._handleVNCAuth, 16)
        else:
            log.msg(f"unknown auth response ({auth})")

    def _handleConnFailed(self, block: bytes) -> None:
        (waitfor,) = unpack("!I", block)
        self.expect(self._handleConnMessage, waitfor)

    def _handleConnMessage(self, block: bytes) -> None:
        log.msg(f"Connection refused: {block!r}")

    def _handleVNCAuth(self, block: bytes) -> None:
        self._challenge = block
        self.vncRequestPassword()
        self.expect(self._handleVNCAuthResult, 4)

    def _handleDHAuth(self, block: bytes) -> None:
        self.generator, self.keyLen = unpack(f"!HH", block)
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
        kl = self.keyLen
        m = bytes_to_long(self.modulus)
        sk = bytes_to_long(self.serverKey)

        key = long_to_bytes(pow(g,s,m))
        shared = long_to_bytes(pow(sk,s,m))

        h = MD5.new()
        h.update(shared)
        keyDigest = h.digest()

        cipher = AES.new(keyDigest, AES.MODE_ECB)
        ciphertext = cipher.encrypt(userStruct.encode('utf-8'))
        self.transport.write(ciphertext+key)

    def ardRequestCredentials(self) -> None:
        if self.factory.username is None:
            self.factory.username = input('DH username: ')
        if self.factory.password is None:
            self.factory.password = getpass.getpass('DH password:')

    def sendPassword(self, password: str) -> None:
        """send password"""
        pw = f"{password:\0<8.8}"        #make sure its 8 chars long, zero padded
        des = RFBDes(pw.encode("ASCII"))  #unspecified https://www.rfc-editor.org/rfc/rfc6143#section-7.2.2
        response = des.encrypt(self._challenge)
        self.transport.write(response)

    def _handleVNCAuthResult(self, block: bytes) -> None:
        (result,) = unpack("!I", block)
        #~ print(f"{auth=}")
        if result == 0:     #OK
            self._doClientInitialization()
            return
        elif result == 1:   #failed
            if self._version < (3, 8):
                self.vncAuthFailed("authentication failed")
                self.transport.loseConnection()
            else:
                self.expect(self._handleAuthFailed, 4)
        elif result == 2:   #too many
            if self._version < (3, 8):
                self.vncAuthFailed("too many tries to log in")
                self.transport.loseConnection()
            else:
                self.expect(self._handleAuthFailed, 4)
        else:
            log.msg(f"unknown auth response ({result})")

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
        (self.bpp, self.depth, self.bigendian, self.truecolor,
         self.redmax, self.greenmax, self.bluemax,
         self.redshift, self.greenshift, self.blueshift) = \
           unpack("!BBBBHHHBBBxxx", pixformat)
        self.bypp = self.bpp // 8        #calc bytes per pixel
        self.expect(self._handleServerName, namelen)

    def _handleServerName(self, block: bytes) -> None:
        self.name = block
        #callback:
        self.vncConnectionMade()
        self.expect(self._handleConnection, 1)

    #------------------------------------------------------
    # Server to client messages
    #------------------------------------------------------
    def _handleConnection(self, block: bytes) -> None:
        (msgid,) = unpack("!B", block)
        if msgid == 0:
            self.expect(self._handleFramebufferUpdate, 3)
        elif msgid == 2:
            self.bell()
            self.expect(self._handleConnection, 1)
        elif msgid == 3:
            self.expect(self._handleServerCutText, 7)
        else:
            log.msg(f"unknown message received (id {msgid})")
            self.expect(self._handleConnection, 1)

    def _handleFramebufferUpdate(self, block: bytes) -> None:
        (self.rectangles,) = unpack("!xH", block)
        self.rectanglePos: List[Rect] = []
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
        if self.rectangles:
            self.rectangles -= 1
            self.rectanglePos.append( (x, y, width, height) )
            if encoding == Encoding.COPY_RECTANGLE:
                self.expect(self._handleDecodeCopyrect, 4, x, y, width, height)
            elif encoding == Encoding.RAW:
                self.expect(self._handleDecodeRAW, width*height*self.bypp, x, y, width, height)
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
                length += int(math.floor((width + 7.0) / 8)) * height
                self.expect(self._handleDecodePsuedoCursor, length, x, y, width, height)
            elif encoding == Encoding.PSEUDO_DESKTOP_SIZE:
                self._handleDecodeDesktopSize(width, height)
            else:
                log.msg(f"unknown encoding received (encoding {encoding})")
                self._doConnection()
        else:
            self._doConnection()

    # ---  RAW Encoding

    def _handleDecodeRAW(self, block: bytes, x: int, y: int, width: int, height: int) -> None:
        #TODO convert pixel format?
        self.updateRectangle(x, y, width, height, block)
        self._doConnection()

    # ---  CopyRect Encoding

    def _handleDecodeCopyrect(self, block: bytes, x: int, y: int, width: int, height: int) -> None:
        (srcx, srcy) = unpack("!HH", block)
        self.copyRectangle(srcx, srcy, x, y, width, height)
        self._doConnection()

    # ---  RRE Encoding

    def _handleDecodeRRE(self, block: bytes, x: int, y: int, width: int, height: int) -> None:
        (subrects,) = unpack("!I", block[:4])
        color = block[4:]
        self.fillRectangle(x, y, width, height, color)
        if subrects:
            self.expect(self._handleRRESubRectangles, (8 + self.bypp) * subrects, x, y)
        else:
            self._doConnection()

    def _handleRRESubRectangles(self, block: bytes, topx: int, topy: int) -> None:
        #~ print("_handleRRESubRectangle")
        pos = 0
        end = len(block)
        sz  = self.bypp + 8
        format = f"!{self.bypp}sHHHH"
        while pos < end:
            (color, x, y, width, height) = unpack(format, block[pos:pos+sz])
            self.fillRectangle(topx + x, topy + y, width, height, color)
            pos += sz
        self._doConnection()

    # ---  CoRRE Encoding

    def _handleDecodeCORRE(self, block: bytes, x: int, y: int, width: int, height: int) -> None:
        (subrects,) = unpack("!I", block[:4])
        color = block[4:]
        self.fillRectangle(x, y, width, height, color)
        if subrects:
            self.expect(self._handleDecodeCORRERectangles, (4 + self.bypp)*subrects, x, y)
        else:
            self._doConnection()

    def _handleDecodeCORRERectangles(self, block: bytes, topx: int, topy: int) -> None:
        #~ print("_handleDecodeCORRERectangle")
        pos = 0
        end = len(block)
        sz  = self.bypp + 4
        format = "!{self.bypp}sBBBB"
        while pos < sz:
            (color, x, y, width, height) = unpack(format, block[pos:pos+sz])
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
        #~ print("_doNextHextileSubrect %r" % ((color, x, y, width, height, tx, ty),))
        #coords of next tile
        #its line after line of tiles
        #finished when the last line is completly received

        #dont inc the first time
        if tx is not None:
            assert ty is not None
            #calc next subrect pos
            tx += 16
            if tx >= x + width:
                tx = x
                ty += 16
        else:
            tx = x
            ty = y
        #more tiles?
        if ty >= y + height:
            self._doConnection()
        else:
            self.expect(self._handleDecodeHextile, 1, bg, color, x, y, width, height, tx, ty)

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
        (subencoding,) = unpack("!B", block)
        #calc tile size
        tw = th = 16
        if x + width - tx < 16:   tw = x + width - tx
        if y + height - ty < 16:  th = y + height- ty
        #decode tile
        if subencoding & 1:     #RAW
            self.expect(self._handleDecodeHextileRAW, tw*th*self.bypp, bg, color, x, y, width, height, tx, ty, tw, th)
        else:
            numbytes = 0
            if subencoding & 2:     #BackgroundSpecified
                numbytes += self.bypp
            if subencoding & 4:     #ForegroundSpecified
                numbytes += self.bypp
            if subencoding & 8:     #AnySubrects
                numbytes += 1
            if numbytes:
                self.expect(self._handleDecodeHextileSubrect, numbytes, subencoding, bg, color, x, y, width, height, tx, ty, tw, th)
            else:
                self.fillRectangle(tx, ty, tw, th, bg)
                self._doNextHextileSubrect(bg, color, x, y, width, height, tx, ty)

    def _handleDecodeHextileSubrect(
        self,
        block: bytes,
        subencoding: int,
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
        if subencoding & 2:     #BackgroundSpecified
            bg = block[:self.bypp]
            pos += self.bypp
        self.fillRectangle(tx, ty, tw, th, bg)
        if subencoding & 4:     #ForegroundSpecified
            color = block[pos:pos+self.bypp]
            pos += self.bypp
        if subencoding & 8:     #AnySubrects
            #~ (subrects, ) = unpack("!B", block)
            # In python2, block : string, block[pos] : string, ord(block[pos]) : int
            # In python3, block : byte,   block[pos] : int,    ord(block[pos]) : error
            subrects = block[pos]
        #~ print(subrects)
        if subrects:
            if subencoding & 16:    #SubrectsColoured
                self.expect(self._handleDecodeHextileSubrectsColoured, (self.bypp + 2)*subrects, bg, color, subrects, x, y, width, height, tx, ty, tw, th)
            else:
                self.expect(self._handleDecodeHextileSubrectsFG, 2*subrects, bg, color, subrects, x, y, width, height, tx, ty, tw, th)
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
            xy = ord(block[pos2])
            wh = ord(block[pos2+1])
            sx = xy >> 4
            sy = xy & 0xf
            sw = (wh >> 4) + 1
            sh = (wh & 0xf) + 1
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
            wh = block[pos+1]
            sx = xy >> 4
            sy = xy & 0xf
            sw = (wh >> 4) + 1
            sh = (wh & 0xf) + 1
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
            return bytearray((
                next(i),
                next(i),
                next(i),
                0xff,
            ))

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
    def _handleDecodePsuedoCursor(self, block: bytes, x: int, y: int, width: int, height: int) -> None:
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

    def _handleServerCutText(self, block: bytes) -> None:
        (length, ) = unpack("!xxxI", block)
        self.expect(self._handleServerCutTextValue, length)

    def _handleServerCutTextValue(self, block: bytes) -> None:
        self.copy_text(block.decode("iso-8859-1"))
        self.expect(self._handleConnection, 1)

    #------------------------------------------------------
    # incomming data redirector
    #------------------------------------------------------
    def dataReceived(self, data: bytes) -> None:
        #~ sys.stdout.write(repr(data) + '\n')
        #~ print(f"{len(data), {len(self._packet)}")
        self._packet.extend(data)
        self._handler()

    def _handleExpected(self) -> None:
        if len(self._packet) >= self._expected_len:
            while len(self._packet) >= self._expected_len:
                self._already_expecting = True
                block = bytes(self._packet[:self._expected_len])
                del self._packet[:self._expected_len]
                #~ log.msg(f"handle {block!r} with {self._expected_handler.__name__!r}")
                self._expected_handler(block, *self._expected_args, **self._expected_kwargs)
            self._already_expecting = False

    def expect(self, handler: Callable[..., None], size: int, *args: Any, **kwargs: Any) -> None:
        #~ log.msg(f"expect({handler.__name__!r}, {size!r}, {args!r}, {kwargs!r})")
        self._expected_handler = handler
        self._expected_len = size
        self._expected_args = args
        self._expected_kwargs = kwargs
        if not self._already_expecting:
            self._handleExpected()   #just in case that there is already enough data

    #------------------------------------------------------
    # client -> server messages
    #------------------------------------------------------

    def setPixelFormat(
        self,
        bpp: int = 32,
        depth: int = 24,
        bigendian: bool = False,
        truecolor: bool = True,
        redmax: int = 255,
        greenmax: int = 255,
        bluemax: int = 255,
        redshift: int = 0,
        greenshift: int = 8,
        blueshift: int = 16
    ) -> None:
        pixformat = pack("!BBBBHHHBBBxxx", bpp, depth, bigendian, truecolor, redmax, greenmax, bluemax, redshift, greenshift, blueshift)
        self.transport.write(pack("!Bxxx16s", 0, pixformat))
        #rember these settings
        self.bpp, self.depth, self.bigendian, self.truecolor = bpp, depth, bigendian, truecolor
        self.redmax, self.greenmax, self.bluemax = redmax, greenmax, bluemax
        self.redshift, self.greenshift, self.blueshift = redshift, greenshift, blueshift
        self.bypp = self.bpp // 8        #calc bytes per pixel
        #~ print(self.bypp)

    def setEncodings(self, list_of_encodings: Collection[Encoding]) -> None:
        self.transport.write(pack("!BxH", 2, len(list_of_encodings)))
        for encoding in list_of_encodings:
            self.transport.write(pack("!i", encoding))

    def framebufferUpdateRequest(
        self,
        x: int = 0,
        y: int = 0,
        width: Optional[int] = None,
        height: Optional[int] = None,
        incremental: bool = False,
    ) -> None:
        if width  is None: width  = self.width - x
        if height is None: height = self.height - y
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

    #------------------------------------------------------
    # callbacks
    # override these in your application
    #------------------------------------------------------
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

    def updateRectangle(self, x: int, y: int, width: int, height: int, data: bytes) -> None:
        """new bitmap data. data is a string in the pixel format set
           up earlier."""

    def copyRectangle(self, srcx: int, srcy: int, x: int, y: int, width: int, height: int) -> None:
        """used for copyrect encoding. copy the given rectangle
           (src, srxy, width, height) to the target coords (x,y)"""

    def fillRectangle(self, x: int, y: int, width: int, height: int, color: bytes) -> None:
        """fill the area with the color. the color is a string in
           the pixel format set up earlier"""
        #fallback variant, use update recatngle
        #override with specialized function for better performance
        self.updateRectangle(x, y, width, height, color * width * height)

    def updateCursor(self, x: int, y: int, width: int, height: int, image: bytes, mask: bytes) -> None:
        """ New cursor, focuses at (x, y)
        """

    def updateDesktopSize(self, width: int, height: int) -> None:
        """ New desktop size of width*height. """

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

class RFBDes(pyDes.des):
    def setKey(self, key: bytes) -> None:
        """RFB protocol for authentication requires client to encrypt
           challenge sent by server with password using DES method. However,
           bits in each byte of the password are put in reverse order before
           using it as encryption key."""
        newkey = bytes(
            sum((128 >> i) if (k & (1 << i)) else 0 for i in range(8))
            for k in key
        )
        super().setKey(newkey)


# --- test code only, see vncviewer.py

if __name__ == '__main__':
    class RFBTest(RFBClient):
        """dummy client"""
        def vncConnectionMade(self) -> None:
            print(f"Screen format: depth={self.depth} bytes_per_pixel={self.bpp}")
            print(f"Desktop name: {self.name!r}")
            self.SetEncodings([Encoding.RAW])
            self.FramebufferUpdateRequest()

        def updateRectangle(self, x: int, y: int, width: int, height: int, data: bytes) -> None:
            print("%s " * 5 % (x, y, width, height, repr(data[:20])))

    class RFBTestFactory(protocol.ClientFactory):  # type: ignore[misc]
        """test factory"""
        protocol = RFBTest
        def clientConnectionLost(self, connector: IConnector, reason: Failure) -> None:
            print(reason)
            from twisted.internet import reactor
            reactor.stop()
            #~ connector.connect()

        def clientConnectionFailed(self, connector: IConnector, reason: Failure) -> None:
            print("connection failed:", reason)
            from twisted.internet import reactor
            reactor.stop()

    class Options(usage.Options):  # type: ignore[misc]
        """command line options"""
        optParameters = [
            ['display',     'd', '0',               'VNC display'],
            ['host',        'h', 'localhost',       'remote hostname'],
            ['outfile',     'o', None,              'Logfile [default: sys.stdout]'],
        ]

    o = Options()
    try:
        o.parseOptions()
    except usage.UsageError as errortext:
        print(f"{sys.argv[0]}: {errortext}")
        print(f"{sys.argv[0]}: Try --help for usage details.")
        raise SystemExit(1)

    logFile = sys.stdout
    if o.opts['outfile']:
        logFile = o.opts['outfile']
    log.startLogging(logFile)

    host = o.opts['host']
    port = int(o.opts['display']) + 5900

    application = service.Application("rfb test") # create Application

    # connect to this host and port, and reconnect if we get disconnected
    vncClient = internet.TCPClient(host, port, RFBFactory()) # create the service
    vncClient.setServiceParent(application)

    # this file should be run as 'twistd -y rfb.py' but it didn't work -
    # could't import crippled_des.py, so using this hack.
    # now with crippled_des.py replaced with pyDes this can be no more actual
    from twisted.internet import reactor
    vncClient.startService()
    reactor.run()
