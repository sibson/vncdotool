"""
Twisted based VNC client protocol and factory.
"""
# (c) 2010-2024 Marc Sibson
#
# MIT License

from __future__ import annotations

import logging
import socket
from pathlib import Path
from struct import pack
from typing import IO, Any, Callable, Iterator, TypeVar, Union, cast

from twisted.internet import reactor
from twisted.internet.defer import Deferred, inlineCallbacks, returnValue
from twisted.internet.endpoints import HostnameEndpoint, UNIXClientEndpoint
from twisted.internet.interfaces import IConnector, ITCPTransport
from twisted.internet.protocol import connectionDone
from twisted.python.failure import Failure

from . import decoders, pixelformat, rfb, websocket
from .const import JPEG_QUALITY_ENCODINGS
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

    from . import imagematch
except ImportError:
    class _RuntimeImportError:
        def __getattr__(self, _: str) -> Any:
            raise ImportError("PIL")

    Image = _RuntimeImportError()  # type: ignore[assignment]
    imagematch = _RuntimeImportError()  # type: ignore[assignment]
    PIL = _RuntimeImportError()


class VNCDoException(Exception):
    pass


class AuthenticationError(VNCDoException):
    """VNC Server requires Authentication"""


class ProtocolError(VNCDoException):
    """VNC Server sent something we cannot handle"""


class RegionError(VNCDoException):
    """A region to compare or capture is not on the screen"""


class _StableWatch:
    """Bookkeeping for one :meth:`VNCDoToolClient.stableScreen` call.

    Waits for a trailing window of ``seconds`` in which no framebuffer update
    moved the screen further than ``fuzz`` from the frame before it.  See
    ``specs/screen-stability.md``.
    """

    def __init__(
        self,
        client: "VNCDoToolClient",
        seconds: float,
        fuzz: int,
        blur: int,
        box: tuple[int, int, int, int] | None = None,
    ) -> None:
        self.client = client
        self.seconds = seconds
        self.fuzz = fuzz
        self.blur = blur
        self.box = box
        self.baseline: Image.Image | None = None
        self.result: Deferred = Deferred()
        self.timer: Any = None
        self.settled = False

    def start(self) -> Deferred:
        if self.client.screen is not None:
            self.baseline = self._frame()
            self._restart()
            self._request(incremental=True)
        else:
            # Nothing to compare against yet; ask for the whole screen and
            # start the window once a frame has arrived.
            self._request(incremental=False)
        return self.result

    def _frame(self) -> Image.Image:
        screen = self.client.screen
        assert screen is not None
        # updateRectangle pastes into self.screen, so an un-copied reference
        # would change underfoot and never compare as different.
        return screen.crop(self.box) if self.box else screen.copy()

    def _request(self, incremental: bool) -> None:
        d: Deferred = Deferred()
        d.addCallback(self._update)
        self.client.deferred = d
        self.client.framebufferUpdateRequest(incremental=incremental)

    def _update(self, _: object) -> None:
        if self.settled:
            return
        frame = self._frame()
        if self.baseline is None or self._changed(frame):
            self.baseline = frame
            self._restart()
        self._request(incremental=True)

    def _changed(self, frame: Image.Image) -> bool:
        assert self.baseline is not None
        return not imagematch.matches(frame, self.baseline, self.fuzz, self.blur)

    def _restart(self) -> None:
        if self.timer is not None and self.timer.active():
            self.timer.reset(self.seconds)
        else:
            self.timer = reactor.callLater(self.seconds, self._settle)

    def _settle(self) -> None:
        self.settled = True
        self.result.callback(self.client)


class VNCDoToolClient(rfb.RFBClient):
    requested_encodings: list[rfb.Encoding] | None = None
    requested_pixel_format: rfb.PixelFormat | None = None
    requested_jpeg_quality: int | None = None
    fuzz: int | None = None
    blur: int = 0
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

    def connectionLost(self, reason: Failure = connectionDone) -> None:
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
        """Capture and save the current VNC screen display to a file.

        :param incremental: if True, only wait for regions that have changed
            since the last capture, rather than the whole screen.
        :param format: a Pillow image format; see Pillow's list of `image
            file formats <https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html>`_.
            Defaults to whatever Pillow infers from ``fp``'s file name.
        """
        log.debug("captureScreen %s", fp)
        return self._capture(fp, incremental, format=format)

    def captureRegion(
        self, fp: TFile, x: int, y: int, w: int, h: int, incremental: bool = False
    ) -> Deferred:
        """Save a region of the current display to filename"""
        log.debug("captureRegion %s", fp)
        self._requireOnScreen((x, y, x + w, y + h))
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

    def _requireOnScreen(self, box: tuple[int, int, int, int]) -> None:
        """Raise unless a region to crop lies on the screen.

        ``Image.crop`` pads whatever falls outside the image with black
        rather than failing, so an off-screen region compares against black
        and captures it.
        """
        width, height = self.screen.size if self.screen else (self.width, self.height)
        if box[0] < 0 or box[1] < 0 or box[2] > width or box[3] > height:
            raise RegionError(f"region {box} is not inside the {width}x{height} screen")

    def _captureSave(
        self: TClient, data: object, fp: TFile, *args: int, format: str | None = None
    ) -> TClient:
        log.debug("captureSave %s", fp)
        assert self.screen is not None
        if args:
            self._requireOnScreen(args)  # type: ignore[arg-type]
            capture = self.screen.crop(args)  # type: ignore[arg-type]
        else:
            capture = self.screen
        capture.save(fp, format=format)

        return self

    def expectScreen(
        self, filename: str, fuzz: int | None = None, blur: int | None = None
    ) -> Deferred:
        """Wait until the display matches a target image

        :param filename: an image file to read and compare against.
        :param fuzz: how far any one pixel may sit from the target, a whole
            number from 0 (exact) to 255, as a perceived colour difference
            where 255 is the furthest apart two pixels can be. Defaults to
            what the negotiated pixel format cannot express.
        :param blur: blur both screens by this radius before comparing, which
            is what carries a match through a lossy encoding.
        """
        log.debug("expectScreen %s", filename)
        return self._expectFramebuffer(filename, 0, 0, fuzz, blur)

    def expectRegion(
        self, filename: str, x: int, y: int, fuzz: int | None = None, blur: int | None = None
    ) -> Deferred:
        """Wait until a portion of the screen matches the target image

        The region compared is defined by the box
        (x, y), (x + image.width, y + image.height)

        :param fuzz: how far any one pixel may sit from the target, a whole
            number from 0 (exact) to 255, as a perceived colour difference
            where 255 is the furthest apart two pixels can be. Defaults to
            what the negotiated pixel format cannot express.
        :param blur: blur both screens by this radius before comparing, which
            is what carries a match through a lossy encoding.
        """
        log.debug("expectRegion %s (%s, %s)", filename, x, y)
        return self._expectFramebuffer(filename, x, y, fuzz, blur)

    def stableScreen(
        self, seconds: float, fuzz: int | None = None, blur: int | None = None
    ) -> Deferred:
        """Wait until the display stops changing

        :param seconds: length of the trailing window during which the screen
            must not have changed.  The call takes at least this long, and
            longer whenever an update restarts the window.
        :param fuzz: how far any one pixel may sit from where it was in the
            previous frame and still count as unchanged, on the scale
            :meth:`expectScreen` takes, and with the same default.
        :param blur: blur both frames by this radius before comparing.
        """
        log.debug("stableScreen %f", seconds)
        return _StableWatch(
            self, seconds, self._fuzz(fuzz), self._blur(blur)
        ).start()

    def stableRegion(
        self,
        seconds: float,
        x: int,
        y: int,
        w: int,
        h: int,
        fuzz: int | None = None,
        blur: int | None = None,
    ) -> Deferred:
        """Wait until a region of the display stops changing"""
        log.debug("stableRegion %f (%s, %s)", seconds, x, y)
        box = (x, y, x + w, y + h)
        self._requireOnScreen(box)
        return _StableWatch(
            self, seconds, self._fuzz(fuzz), self._blur(blur), box
        ).start()

    def _expectFramebuffer(
        self, filename: str, x: int, y: int, fuzz: int | None, blur: int | None
    ) -> Deferred:
        image = Image.open(filename)
        w, h = image.size
        self.expected_image = image.convert("RGB")

        return self._expectCompare(
            None, (x, y, x + w, y + h), self._fuzz(fuzz), self._blur(blur)
        )

    def _fuzz(self, fuzz: int | None) -> int:
        """A server sending 5-bit red cannot reproduce most 8-bit values, so an
        exact comparison never comes true however long it is polled for.
        """
        if fuzz is not None:
            return fuzz
        if self.fuzz is not None:
            return self.fuzz
        try:
            return imagematch.fuzz_for_format(self.pixel_format)
        except pixelformat.UnsupportedPixelFormat:
            return 0

    def _blur(self, blur: int | None) -> int:
        return self.blur if blur is None else blur

    def _expectCompare(
        self, data: object, box: tuple[int, int, int, int], fuzz: int, blur: int
    ) -> Deferred:
        self._requireOnScreen(box)
        incremental = False
        if self.screen:
            incremental = True
            if imagematch.matches(self.screen.crop(box), self.expected_image, fuzz, blur):
                return self

        self.deferred = Deferred()
        self.deferred.addCallback(self._expectCompare, box, fuzz, blur)
        self.framebufferUpdateRequest(
            incremental=incremental
        )

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
        encodings = list(self.requested_encodings or decoders.DEFAULT_ENCODINGS)
        if self.factory.pseudocursor or self.factory.nocursor:
            encodings.append(rfb.Encoding.PSEUDO_CURSOR)
        if self.factory.pseudodesktop:
            encodings.append(rfb.Encoding.PSEUDO_DESKTOP_SIZE)
        if self.factory.last_rect:
            encodings.append(rfb.Encoding.PSEUDO_LAST_RECT)
        if self.factory.qemu_extended_key:
            encodings.append(rfb.Encoding.PSEUDO_QEMU_EXTENDED_KEY_EVENT)
        if self.factory.fence:
            encodings.append(rfb.Encoding.PSEUDO_FENCE)
        if self.requested_jpeg_quality is not None:
            encodings.append(JPEG_QUALITY_ENCODINGS[self.requested_jpeg_quality])
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
            self.cmask = None
            return

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
        self.width, self.height = width, height


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
    # Nothing here initiates a fence or waits on one, so offering the encoding
    # would only invite traffic the client discards.
    fence = False
    force_caps = False
    pixel_format: rfb.PixelFormat | None = None
    encodings: list[rfb.Encoding] | None = None
    jpeg_quality: int | None = None
    fuzz: int | None = None
    blur: int = 0

    def __init__(self) -> None:
        self.deferred = Deferred()
        self._disconnect_callbacks: list[Callable[[Failure], None]] = []

    def buildProtocol(self, addr: object) -> VNCDoToolClient:
        protocol = cast("VNCDoToolClient", super().buildProtocol(addr))
        protocol.requested_pixel_format = self.pixel_format
        protocol.requested_encodings = self.encodings
        protocol.requested_jpeg_quality = self.jpeg_quality
        protocol.fuzz = self.fuzz
        protocol.blur = self.blur
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
    factory: VNCDoToolFactory, host: str, port: int, family: websocket.AddressFamily
) -> None:
    if family is websocket.WEBSOCKET:
        # host carries the whole URL: the path and query select the session.
        conn = websocket.connect(reactor, factory, host)
    elif family in {socket.AF_UNSPEC, socket.AF_INET, socket.AF_INET6}:
        # A connected transport keeps only the resolved address, so the name
        # an X509 certificate must be issued for is recorded before dialling.
        factory.tls_hostname = host
        conn = HostnameEndpoint(reactor, host, port).connect(factory)
    elif hasattr(socket, "AF_UNIX") and family == socket.AF_UNIX:
        conn = UNIXClientEndpoint(reactor, host).connect(factory)
    else:
        raise ValueError(family)

    # conn.addCallback(factory.clientConnectionMade) already called by VNCDoToolClient.vncConnectionMade()
    conn.addErrback(lambda reason: factory.clientConnectionFailed(None, reason))
