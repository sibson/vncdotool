"""
Twisted based VNC client protocol and factory.
"""
# (c) 2010-2024 Marc Sibson
#
# MIT License

from __future__ import annotations

import logging
import math
import socket
import warnings
from pathlib import Path
from struct import pack
from typing import IO, Any, Callable, Iterator, TypeVar, Union

from twisted.internet import reactor
from twisted.internet.defer import Deferred, inlineCallbacks, returnValue
from twisted.internet.endpoints import HostnameEndpoint, UNIXClientEndpoint
from twisted.internet.interfaces import IConnector, ITCPTransport
from twisted.python.failure import Failure

from . import pixelformat, rfb
from .keys import KEYMAP

TClient = TypeVar("TClient", bound="VNCDoToolClient")
TFile = Union[str, Path, IO[bytes]]

log = logging.getLogger(__name__)

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


class ProtocolError(VNCDoException):
    """VNC Server sent something we cannot handle"""


class VNCDoToolClient(rfb.RFBClient):
    encoding = rfb.Encoding.RAW
    requested_encodings: list[rfb.Encoding] | None = None
    requested_pixel_format: rfb.PixelFormat | None = None
    x = 0
    y = 0
    buttons = 0
    screen: Image.Image | None = None
    _image_mode = pixelformat.raw_mode(rfb.PixelFormat())
    _raw_mode_format: rfb.PixelFormat | None = None
    _raw_mode = ""
    deferred: Deferred | None = None

    cursor: Image.Image | None = None
    cmask: Image.Image | None = None

    SPECIAL_KEYS_US = '~!@#$%^&*()_+{}|:"<>?'
    MAX_DESKTOP_SIZE = 0x10000

    def connectionMade(self) -> None:
        super().connectionMade()

        if isinstance(self.transport, ITCPTransport):
            self.transport.setTcpNoDelay(True)

    def connectionLost(self, reason: Failure) -> None:
        super().connectionLost(reason)
        self.factory.clientConnectionLost(self, reason)

    def _decodeKey(self, key: str) -> list[int]:
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

        :param key: either [a-z] or a from :const:`KEYMAP`.
        """
        keys = self._decodeKey(key)
        log.debug("keyPress %s", keys)
        for k in keys:
            self.keyEvent(k, down=True)
        for k in reversed(keys):
            self.keyEvent(k, down=False)

        return self

    def keyDown(self: TClient, key: str) -> TClient:
        keys = self._decodeKey(key)
        log.debug("keyDown %s", keys)
        for k in keys:
            self.keyEvent(k, down=True)

        return self

    def keyUp(self: TClient, key: str) -> TClient:
        keys = self._decodeKey(key)
        log.debug("keyUp %s", keys)
        for k in keys:
            self.keyEvent(k, down=False)

        return self

    def mousePress(self: TClient, button: int) -> TClient:
        """Send a mouse click at the last set position

        :param button: [1-n]
        """
        log.debug("mousePress %s", button)
        self.mouseDown(button)
        self.mouseUp(button)

        return self

    def mouseDown(self: TClient, button: int) -> TClient:
        """Send a mouse button down at the last set position

        :param button: [1-n]
        """
        log.debug("mouseDown %s", button)
        self.buttons |= 1 << (button - 1)
        self.pointerEvent(self.x, self.y, buttonmask=self.buttons)

        return self

    def mouseUp(self: TClient, button: int) -> TClient:
        """Send mouse button released at the last set position

        :param button: [1-n]
        """
        log.debug("mouseUp %s", button)
        self.buttons &= ~(1 << (button - 1))
        self.pointerEvent(self.x, self.y, buttonmask=self.buttons)

        return self

    def captureScreen(
        self, fp: TFile, incremental: bool = False, format: str | None = None
    ) -> Deferred:
        """
        Capture and save the current VNC screen display to a file.

        Parameters:
            fp (TFile): The destination where the screenshot will be saved.
                        It can be a string path, a `pathlib.Path` object, or a file-like object opened in binary mode.
            incremental (bool, optional):
                - `False` (default): Captures the entire screen.
                - `True`: Captures only the regions of the screen that have changed since the last capture.
            format (str | None, optional):
                - See Pillow's list of image formats: https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html
                - If set to `None`, Pillow will determine the format based on the provided file name.
        """
        log.debug("captureScreen %s", fp)
        return self._capture(fp, incremental, format=format)

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

    def _capture(
        self, fp: TFile, incremental: bool, *args: int, format: str | None = None
    ) -> Deferred:
        d = self.refreshScreen(incremental)
        kwargs = {"format": format} if format else {}
        d.addCallback(self._captureSave, fp, *args, **kwargs)
        return d

    def _captureSave(
        self: TClient, data: object, fp: TFile, *args: int, format: str | None = None
    ) -> TClient:
        log.debug("captureSave %s", fp)
        assert self.screen is not None
        if args:
            capture = self.screen.crop(args)  # type: ignore[arg-type]
        else:
            capture = self.screen
        capture.save(fp, format=format)

        return self

    def expectScreen(self, filename: str, maxrms: float = 0) -> Deferred:
        """Wait until the display matches a target image

        :param filename: an image file to read and compare against.
        :param maxrms: the maximum root mean square between histograms of the screen and target image.
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

    def _expectCompare(self, data: object, box: tuple[int, int, int, int], maxrms: float) -> Deferred:
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

    @inlineCallbacks
    def mouseDrag(self: TClient, x: int, y: int, step: int = 1) -> Iterator[Deferred]:
        """Move the mouse point to position (x, y) in increments of step"""
        log.debug("mouseDrag %d,%d", x, y)
        ox, oy = self.x, self.y
        dx, dy = x - ox, y - oy
        dmax = max(abs(dx), abs(dy))
        for s in range(0, dmax, step):
            self.mouseMove(ox + dx * s // dmax, oy + dy * s // dmax)
            yield self.pause(0.2)

        self.mouseMove(x, y)

        returnValue(self)

    @property
    def image_mode(self) -> str:
        warnings.warn(
            "image_mode will change in a future release; please comment on "
            "https://github.com/sibson/vncdotool/issues/385 if you rely on it",
            FutureWarning,
            stacklevel=2,
        )
        return self._image_mode

    def _rawModeFor(self, pixel_format: rfb.PixelFormat) -> str:
        # Called once per rectangle. A PixelFormat is a frozen dataclass, so
        # hashing one for a cache lookup costs more than the identity check
        # a decoder handing back the same instance every time satisfies.
        if pixel_format is not self._raw_mode_format:
            self._raw_mode_format = pixel_format
            self._raw_mode = pixelformat.raw_mode(pixel_format)
        return self._raw_mode

    def setImageMode(self) -> None:
        """Check support for PixelFormats announced by server or select client supported alternative."""
        pixel_format = self.requested_pixel_format
        if pixel_format is None:
            try:
                self._image_mode = pixelformat.raw_mode(self.pixel_format)
                return
            except pixelformat.UnsupportedPixelFormat as exc:
                log.debug("cannot unpack the server's format (%s), asking for another", exc)
                if self._version_server == (3, 889):  # Apple Remote Desktop
                    pixel_format = pixelformat.PIXEL_FORMATS["rgb565"]
                else:
                    pixel_format = pixelformat.PIXEL_FORMATS["rgbx8888"]

        # Resolved before the request goes out: failing afterwards would
        # leave the server sending pixels in a format we cannot read.
        try:
            image_mode = pixelformat.raw_mode(pixel_format)
        except pixelformat.UnsupportedPixelFormat as exc:
            self.vncProtocolError(f"cannot decode the requested pixel format: {exc}")
            self.transport.loseConnection()
            return

        self.setPixelFormat(pixel_format)
        self._image_mode = image_mode

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

    def vncAuthFailed(self, reason: bytes | str) -> None:
        super().vncAuthFailed(reason)
        if isinstance(reason, bytes):
            reason = reason.decode("utf-8", "replace")
        self.factory.clientConnectionFailed(self, Failure(AuthenticationError(reason)))

    def vncProtocolError(self, reason: str) -> None:
        super().vncProtocolError(reason)
        self.factory.clientConnectionFailed(self, Failure(ProtocolError(reason)))

    def vncConnectionMade(self) -> None:
        self.setImageMode()
        encodings = list(self.requested_encodings or [self.encoding])
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
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        data: bytes,
        pixel_format: rfb.PixelFormat,
    ) -> None:
        # ignore empty updates
        if not data:
            return

        size = (width, height)
        update = Image.frombytes(
            "RGB", size, data, "raw", self._rawModeFor(pixel_format)
        )
        if not self.screen:
            self.screen = Image.new("RGB", (self.width, self.height), "black")
            self.screen.paste(update, (x, y))
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

    def copyRectangle(
        self, srcx: int, srcy: int, x: int, y: int, width: int, height: int
    ) -> None:
        if self.screen is None:
            return
        region = self.screen.crop((srcx, srcy, srcx + width, srcy + height))
        self.screen.paste(region, (x, y))
        self.drawCursor()

    def commitUpdate(self, rectangles: list[tuple[int, int, int, int]] | None = None) -> None:
        if self.deferred:
            if not rectangles:
                # No rectangle in this update painted self.screen; wait for
                # one that does before completing the refresh.
                self.framebufferUpdateRequest()
                return
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
            "RGB", (width, height), image, "raw", self._image_mode
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
    SINGLE_PIXEL_UPDATE = pack(
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
    username: str | None = None
    password: str | None = None

    protocol = VNCDoToolClient
    shared = True

    pseudocursor = False
    nocursor = False
    pseudodesktop = True
    qemu_extended_key = True
    last_rect = True
    force_caps = False
    pixel_format: rfb.PixelFormat | None = None
    encodings: list[rfb.Encoding] | None = None

    def __init__(self) -> None:
        self.deferred = Deferred()
        self._disconnect_callbacks: list[Callable[[Failure], None]] = []

    def buildProtocol(self, addr: object) -> VNCDoToolClient:
        protocol = super().buildProtocol(addr)
        protocol.requested_pixel_format = self.pixel_format
        protocol.requested_encodings = self.encodings
        return protocol

    def clientConnectionLost(self, connector: IConnector, reason: Failure) -> None:
        for cb in self._disconnect_callbacks:
            cb(reason)
        self._disconnect_callbacks.clear()

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
