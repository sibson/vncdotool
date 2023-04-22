"""
Twisted based VNC client protocol and factory

(c) 2010 Marc Sibson

MIT License
"""

import logging
import math
import socket
import time
from pathlib import Path
from struct import pack
from typing import IO, Any, List, Optional, TypeVar, Union

from twisted.internet import reactor
from twisted.internet.defer import Deferred
from twisted.internet.endpoints import HostnameEndpoint, UNIXClientEndpoint
from twisted.internet.interfaces import IConnector, ITCPTransport
from twisted.python.failure import Failure

from . import rfb

TClient = TypeVar("TClient", bound="VNCDoToolClient")
TFile = Union[str, Path, IO[bytes]]

log = logging.getLogger(__name__)


KEYMAP = {
    "bsp": rfb.KEY_BackSpace,
    "tab": rfb.KEY_Tab,
    "return": rfb.KEY_Return,
    "enter": rfb.KEY_Return,
    "esc": rfb.KEY_Escape,
    "ins": rfb.KEY_Insert,
    "delete": rfb.KEY_Delete,
    "del": rfb.KEY_Delete,
    "home": rfb.KEY_Home,
    "end": rfb.KEY_End,
    "pgup": rfb.KEY_PageUp,
    "pgdn": rfb.KEY_PageDown,
    "left": rfb.KEY_Left,
    "up": rfb.KEY_Up,
    "right": rfb.KEY_Right,
    "down": rfb.KEY_Down,
    "slash": rfb.KEY_BackSlash,
    "bslash": rfb.KEY_BackSlash,
    "fslash": rfb.KEY_ForwardSlash,
    "spacebar": rfb.KEY_SpaceBar,
    "space": rfb.KEY_SpaceBar,
    "sb": rfb.KEY_SpaceBar,
    "f1": rfb.KEY_F1,
    "f2": rfb.KEY_F2,
    "f3": rfb.KEY_F3,
    "f4": rfb.KEY_F4,
    "f5": rfb.KEY_F5,
    "f6": rfb.KEY_F6,
    "f7": rfb.KEY_F7,
    "f8": rfb.KEY_F8,
    "f9": rfb.KEY_F9,
    "f10": rfb.KEY_F10,
    "f11": rfb.KEY_F11,
    "f12": rfb.KEY_F12,
    "f13": rfb.KEY_F13,
    "f14": rfb.KEY_F14,
    "f15": rfb.KEY_F15,
    "f16": rfb.KEY_F16,
    "f17": rfb.KEY_F17,
    "f18": rfb.KEY_F18,
    "f19": rfb.KEY_F19,
    "f20": rfb.KEY_F20,
    "lshift": rfb.KEY_ShiftLeft,
    "shift": rfb.KEY_ShiftLeft,
    "rshift": rfb.KEY_ShiftRight,
    "lctrl": rfb.KEY_ControlLeft,
    "ctrl": rfb.KEY_ControlLeft,
    "rctrl": rfb.KEY_ControlRight,
    "lmeta": rfb.KEY_MetaLeft,
    "meta": rfb.KEY_MetaLeft,
    "rmeta": rfb.KEY_MetaRight,
    "lalt": rfb.KEY_AltLeft,
    "alt": rfb.KEY_AltLeft,
    "ralt": rfb.KEY_AltRight,
    "scrlk": rfb.KEY_Scroll_Lock,
    "sysrq": rfb.KEY_Sys_Req,
    "numlk": rfb.KEY_Num_Lock,
    "caplk": rfb.KEY_Caps_Lock,
    "pause": rfb.KEY_Pause,
    "lsuper": rfb.KEY_Super_L,
    "super": rfb.KEY_Super_L,
    "rsuper": rfb.KEY_Super_R,
    "lhyper": rfb.KEY_Hyper_L,
    "hyper": rfb.KEY_Hyper_L,
    "rhyper": rfb.KEY_Hyper_R,
    "kp0": rfb.KEY_KP_0,
    "kp1": rfb.KEY_KP_1,
    "kp2": rfb.KEY_KP_2,
    "kp3": rfb.KEY_KP_3,
    "kp4": rfb.KEY_KP_4,
    "kp5": rfb.KEY_KP_5,
    "kp6": rfb.KEY_KP_6,
    "kp7": rfb.KEY_KP_7,
    "kp8": rfb.KEY_KP_8,
    "kp9": rfb.KEY_KP_9,
    "kpenter": rfb.KEY_KP_Enter,
}

# Enable using vncdotool without PIL. Of course capture and expect
# won't work but at least we can still offer key, type, press and
# move.
try:
    from PIL import Image

    # Init PIL to make sure it will not try to import plugin libraries
    # in a thread.
    Image.preinit()
    Image.init()
except ImportError:
    # If there is no PIL, raise ImportError where someone tries to use
    # it.
    class _RuntimeImportError:
        def __getattr__(self, _: str) -> Any:
            raise ImportError("PIL")

    Image = _RuntimeImportError()  # type: ignore[assignment]
    PIL = _RuntimeImportError()


class VNCDoException(Exception):
    pass


class AuthenticationError(VNCDoException):
    """VNC Server requires Authentication"""


RGB32 = rfb.PixelFormat(32, 24, False, True, 255, 255, 255, 0, 8, 16)
RGB24 = rfb.PixelFormat(24, 24, False, True, 255, 255, 255, 0, 8, 16)
BGR16 = rfb.PixelFormat(16, 16, False, True, 31, 63, 31, 11, 5, 0)
PF2IM = {
    RGB24: "RGB",
    RGB32: "RGBX",
    BGR16: "BGR;16",
    rfb.PixelFormat(24, 24, False, True, 255, 255, 255, 16, 8, 0): "BGR",
    rfb.PixelFormat(32, 24, False, True, 255, 255, 255, 16, 8, 0): "BGRX",
}


class VNCDoToolClient(rfb.RFBClient):
    encoding = rfb.Encoding.RAW
    x = 0
    y = 0
    buttons = 0
    screen: Optional[Image.Image] = None
    image_mode = PF2IM[rfb.PixelFormat()]
    deferred: Optional[Deferred] = None

    cursor: Optional[Image.Image] = None
    cmask: Optional[Image.Image] = None

    SPECIAL_KEYS_US = '~!@#$%^&*()_+{}|:"<>?'
    MAX_DESKTOP_SIZE = 0x10000

    def connectionMade(self) -> None:
        super().connectionMade()

        if isinstance(self.transport, ITCPTransport):
            self.transport.setTcpNoDelay(True)

    def connectionLost(self, reason: Failure) -> None:
        super().connectionLost(reason)
        self.factory.clientConnectionLost(self, reason)

    def _decodeKey(self, key: str) -> List[int]:
        if self.factory.force_caps:
            if key.isupper() or key in self.SPECIAL_KEYS_US:
                key = "shift-%c" % key

        if len(key) == 1:
            keys = [key]
        else:
            keys = key.split("-")

        return [KEYMAP.get(k) or ord(k) for k in keys]

    def pause(self, duration: float) -> Deferred:
        d = Deferred()
        reactor.callLater(duration, d.callback, self)
        return d

    def keyPress(self: TClient, key: str) -> TClient:
        """Send a key press to the server

        key: string: either [a-z] or a from KEYMAP
        """
        log.debug("keyPress %s", key)
        self.keyDown(key)
        self.keyUp(key)

        return self

    def keyDown(self: TClient, key: str) -> TClient:
        log.debug("keyDown %s", key)
        keys = self._decodeKey(key)
        for k in keys:
            self.keyEvent(k, down=True)

        return self

    def keyUp(self: TClient, key: str) -> TClient:
        log.debug("keyUp %s", key)
        keys = self._decodeKey(key)
        for k in keys:
            self.keyEvent(k, down=False)

        return self

    def mousePress(self: TClient, button: int) -> TClient:
        """Send a mouse click at the last set position

        button: int: [1-n]

        """
        log.debug("mousePress %s", button)
        self.mouseDown(button)
        self.mouseUp(button)

        return self

    def mouseDown(self: TClient, button: int) -> TClient:
        """Send a mouse button down at the last set position

        button: int: [1-n]

        """
        log.debug("mouseDown %s", button)
        self.buttons |= 1 << (button - 1)
        self.pointerEvent(self.x, self.y, buttonmask=self.buttons)

        return self

    def mouseUp(self: TClient, button: int) -> TClient:
        """Send mouse button released at the last set position

        button: int: [1-n]

        """
        log.debug("mouseUp %s", button)
        self.buttons &= ~(1 << (button - 1))
        self.pointerEvent(self.x, self.y, buttonmask=self.buttons)

        return self

    def captureScreen(self, fp: TFile, incremental: bool = False) -> Deferred:
        """Save the current display to filename"""
        log.debug("captureScreen %s", fp)
        return self._capture(fp, incremental)

    def captureRegion(
        self, fp: TFile, x: int, y: int, w: int, h: int, incremental: bool = False
    ) -> Deferred:
        """Save a region of the current display to filename"""
        log.debug("captureRegion %s", fp)
        return self._capture(fp, incremental, x, y, x + w, y + h)

    def refreshScreen(self, incremental: bool = False) -> Deferred:
        d = self.deferred = Deferred()
        self.framebufferUpdateRequest(incremental=incremental)
        return d

    def _capture(self, fp: TFile, incremental: bool, *args: int) -> Deferred:
        d = self.refreshScreen(incremental)
        d.addCallback(self._captureSave, fp, *args)
        return d

    def _captureSave(self: TClient, data: object, fp: TFile, *args: int) -> TClient:
        log.debug("captureSave %s", fp)
        assert self.screen is not None
        if args:
            capture = self.screen.crop(args)  # type: ignore[arg-type]
        else:
            capture = self.screen
        capture.save(fp)

        return self

    def expectScreen(self, filename: str, maxrms: float = 0) -> Deferred:
        """Wait until the display matches a target image

        filename: an image file to read and compare against
        maxrms: the maximum root mean square between histograms of the
                screen and target image
        """
        log.debug("expectScreen %s", filename)
        return self._expectFramebuffer(filename, 0, 0, maxrms)

    def expectRegion(
        self, filename: str, x: int, y: int, maxrms: float = 0
    ) -> Deferred:
        """Wait until a portion of the screen matches the target image

        The region compared is defined by the box
        (x, y), (x + image.width, y + image.height)
        """
        log.debug("expectRegion %s (%s, %s)", filename, x, y)
        return self._expectFramebuffer(filename, x, y, maxrms)

    def _expectFramebuffer(
        self, filename: str, x: int, y: int, maxrms: float
    ) -> Deferred:
        image = Image.open(filename)
        w, h = image.size
        self.expected = image.histogram()

        return self._expectCompare(None, (x, y, x + w, y + h), maxrms)

    def _expectCompare(self, data: object, box: rfb.Rect, maxrms: float) -> Deferred:
        incremental = False
        if self.screen:
            incremental = True
            image = self.screen.crop(box)

            hist = image.histogram()
            if len(hist) == len(self.expected):
                sum_ = sum((h - e) ** 2 for h, e in zip(hist, self.expected))
                rms = math.sqrt(sum_ / len(hist))

                log.debug("rms:%f maxrms:%f", rms, maxrms)
                if rms <= maxrms:
                    return self

        self.deferred = Deferred()
        self.deferred.addCallback(self._expectCompare, box, maxrms)
        self.framebufferUpdateRequest(
            incremental=incremental
        )  # use box ~(x, y, w - x, h - y)?

        return self.deferred

    def mouseMove(self: TClient, x: int, y: int) -> TClient:
        """Move the mouse pointer to position (x, y)"""
        log.debug("mouseMove %d,%d", x, y)
        self.x, self.y = x, y
        self.pointerEvent(x, y, self.buttons)
        return self

    def mouseDrag(self: TClient, x: int, y: int, step: int = 1) -> TClient:
        """Move the mouse point to position (x, y) in increments of step"""
        log.debug("mouseDrag %d,%d", x, y)
        if x < self.x:
            xsteps = range(self.x - step, x, -step)
        else:
            xsteps = range(self.x + step, x, step)

        if y < self.y:
            ysteps = range(self.y - step, y, -step)
        else:
            ysteps = range(self.y + step, y, step)

        for ypos in ysteps:
            self.mouseMove(self.x, ypos)
            reactor.doPoll(timeout=5)
            time.sleep(0.2)

        for xpos in xsteps:
            self.mouseMove(xpos, self.y)
            reactor.doPoll(timeout=5)
            time.sleep(0.2)

        self.mouseMove(x, y)

        return self

    def setImageMode(self) -> None:
        """Check support for PixelFormats announced by server or select client supported alternative."""
        try:
            self.image_mode = PF2IM[self.pixel_format]
        except LookupError:
            if self._version_server == (3, 889):  # Apple Remote Desktop
                pixel_format = BGR16
            else:
                pixel_format = RGB32

            self.setPixelFormat(pixel_format)
            self.image_mode = PF2IM[pixel_format]

    #
    # base customizations
    #
    def vncRequestPassword(self) -> None:
        if self.factory.password is None:
            self.transport.loseConnection()
            self.factory.clientConnectionFailed(
                self, AuthenticationError("password required, but none provided")
            )
            return
        self.sendPassword(self.factory.password)

    def vncConnectionMade(self) -> None:
        self.setImageMode()
        encodings = [self.encoding]
        if self.factory.pseudocursor or self.factory.nocursor:
            encodings.append(rfb.Encoding.PSEUDO_CURSOR)
        if self.factory.pseudodesktop:
            encodings.append(rfb.Encoding.PSEUDO_DESKTOP_SIZE)
        if self.factory.last_rect:
            encodings.append(rfb.Encoding.PSEUDO_LAST_RECT)
        if self.factory.qemu_extended_key:
            encodings.append(rfb.Encoding.PSEUDO_QEMU_EXTENDED_KEY_EVENT)
        self.setEncodings(encodings)
        self.factory.clientConnectionMade(self)

    def bell(self) -> None:
        log.info("ding")

    def copy_text(self, text: str) -> None:
        log.info(f"clipboard copy {text!r}")

    def paste(self: TClient, message: str) -> TClient:
        self.clientCutText(message)
        return self

    def updateRectangle(
        self, x: int, y: int, width: int, height: int, data: bytes
    ) -> None:
        # ignore empty updates
        if not data:
            return

        size = (width, height)
        update = Image.frombytes("RGB", size, data, "raw", self.image_mode)
        if not self.screen:
            self.screen = update
        # track upward screen resizes, often occurs during os boot of VMs
        # When the screen is sent in chunks (as observed on VMWare ESXi), the canvas
        # needs to be resized to fit all existing contents and the update.
        elif self.screen.size[0] < (x + width) or self.screen.size[1] < (y + height):
            new_size = (
                max(x + width, self.screen.size[0]),
                max(y + height, self.screen.size[1]),
            )
            new_screen = Image.new("RGB", new_size, "black")
            new_screen.paste(self.screen, (0, 0))
            new_screen.paste(update, (x, y))
            self.screen = new_screen
        else:
            self.screen.paste(update, (x, y))

        self.drawCursor()

    def commitUpdate(self, rectangles: Optional[List[rfb.Rect]] = None) -> None:
        if self.deferred:
            d = self.deferred
            self.deferred = None
            d.callback(self)

    def updateCursor(
        self, x: int, y: int, width: int, height: int, image: bytes, mask: bytes
    ) -> None:
        if self.factory.nocursor:
            return

        if not width or not height:
            self.cursor = None

        self.cursor = Image.frombytes(
            "RGB", (width, height), image, "raw", self.image_mode
        )
        self.cmask = Image.frombytes("1", (width, height), mask)
        self.cfocus = x, y
        self.drawCursor()

    def drawCursor(self) -> None:
        if not self.cursor:
            return

        if not self.screen:
            return

        x = self.x - self.cfocus[0]
        y = self.y - self.cfocus[1]
        self.screen.paste(self.cursor, (x, y), self.cmask)

    def updateDesktopSize(self, width: int, height: int) -> None:
        if not (
            0 <= width < self.MAX_DESKTOP_SIZE and 0 <= height < self.MAX_DESKTOP_SIZE
        ):
            raise ValueError((width, height))
        new_screen = Image.new("RGB", (width, height), "black")
        if self.screen:
            new_screen.paste(self.screen, (0, 0))
        self.screen = new_screen


class VMWareClient(VNCDoToolClient):
    SINGLE_PIXLE_UPDATE = pack(
        "!BxHHHHHixxxx",
        rfb.MsgS2C.FRAMEBUFFER_UPDATE,  # message-type
        # padding
        1,  # number-of-rectangles
        0,  # x-position
        0,  # y.position
        1,  # width
        1,  # height
        rfb.Encoding.RAW,  # encoding-type
        # pixel-data
    )

    def dataReceived(self, data: bytes) -> None:
        # BUG: TCP is a *stream* orianted protocol with no *framing*.
        # Therefore there is no guarantee that these 20 bytes will arrive in one single chunk.
        # This might also match inside any other sequence if fragmentation by chance puts it at be start of a new packet.
        if (
            len(data) == 20
            and data[0] == self.SINGLE_PIXEL_UPDATE[0]
            and data[2:16] == self.SINGLE_PIXEL_UPDATE[2:16]
        ):
            self.framebufferUpdateRequest()
            self._handler()
        else:
            super().dataReceived(data)


class VNCDoToolFactory(rfb.RFBFactory):
    username: Optional[str] = None
    password: Optional[str] = None

    protocol = VNCDoToolClient
    shared = True

    pseudocursor = False
    nocursor = False
    pseudodesktop = True
    qemu_extended_key = True
    last_rect = True
    force_caps = False

    def __init__(self) -> None:
        self.deferred = Deferred()

    def clientConnectionLost(self, connector: IConnector, reason: Failure) -> None:
        pass

    def clientConnectionFailed(self, connector: IConnector, reason: Failure) -> None:
        self.deferred.errback(reason)

    def clientConnectionMade(self, protocol: VNCDoToolClient) -> None:
        self.deferred.callback(protocol)


class VMWareFactory(VNCDoToolFactory):
    protocol = VMWareClient


def factory_connect(
    factory: VNCDoToolFactory, host: str, port: int, family: socket.AddressFamily
) -> None:
    if family in {socket.AF_UNSPEC, socket.AF_INET, socket.AF_INET6}:
        ep = HostnameEndpoint(reactor, host, port)
    elif hasattr(socket, "AF_UNIX") and family == socket.AF_UNIX:
        ep = UNIXClientEndpoint(reactor, host)
    else:
        raise ValueError(family)

    conn = ep.connect(factory)
    # conn.addCallback(factory.clientConnectionMade) already called by VNCDoToolClient.vncConnectionMade()
    conn.addErrback(lambda reason: factory.clientConnectionFailed(None, reason))
