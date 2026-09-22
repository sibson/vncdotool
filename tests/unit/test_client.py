from unittest import TestCase, mock
import io
import struct
import unittest

from PIL import Image
from twisted.internet.task import Clock

from vncdotool import pixelformat, rfb
from vncdotool.client import (
    AuthenticationError,
    DesktopResizeError,
    JPEG_QUALITY_ENCODINGS,
    KasmVNCClient,
    KasmVNCDialect,
    KasmVNCFactory,
    ProtocolError,
    RegionError,
    VMWareClient,
    VNCDoToolClient,
    VNCDoToolFactory,
    apply_dialect,
    log,
)
from vncdotool.cursor import CursorMode
from vncdotool.pixelformat import PIXEL_FORMATS
from vncdotool.keys import Key

COLOUR_MAPPED = rfb.PixelFormat(8, 8, False, False, 0, 0, 0, 0, 0, 0)
RGB24 = rfb.PixelFormat(24, 24, False, True, 255, 255, 255, 0, 8, 16)


class TestVNCDoToolClient(TestCase):

    MSG_HANDSHAKE = b"RFB 003.003\n"
    MSG_INIT = (
        b"\x03\x20"  # width
        b"\x02\x58"  # height
        b"\x20\x18\x00\x01\x00\xff\x00\xff\x00\xff\x00\x08\x10\x00\x00\x00"  # pixel-format
        b"\x00\x00\x00\x00"  # server-name-len
    )

    def setUp(self) -> None:
        self.client = VNCDoToolClient()
        self.client.transport = mock.Mock()
        self.client.factory = mock.Mock()

        self.client.framebufferUpdateRequest = mock.Mock()  # type: ignore[method-assign]
        self.client.pointerEvent = mock.Mock()  # type: ignore[method-assign]
        self.client.keyEvent = mock.Mock()  # type: ignore[method-assign]
        self.client.setEncodings = mock.Mock()  # type: ignore[method-assign]

    def test_connectionLost_accepts_twisted_calling_it_with_no_reason(self):
        self.client.connectionLost()

        self.client.factory.clientConnectionLost.assert_called_once()

    def test_vncConnectionMade(self):
        client = self.client
        client._packet = bytearray(self.MSG_HANDSHAKE)
        client._handleInitial()
        client._handleServerInit(self.MSG_INIT)
        factory = client.factory
        factory.clientConnectionMade.assert_called_once_with(client)
        self.client.setEncodings.assert_called_once_with([
            rfb.Encoding.TIGHT,
            rfb.Encoding.HEXTILE,
            rfb.Encoding.RAW,
            rfb.Encoding.PSEUDO_CURSOR,
            rfb.Encoding.PSEUDO_POINTER_POS,
            rfb.Encoding.PSEUDO_DESKTOP_SIZE,
            rfb.Encoding.PSEUDO_EXTENDED_DESKTOP_SIZE,
            rfb.Encoding.PSEUDO_LAST_RECT,
            rfb.Encoding.PSEUDO_QEMU_EXTENDED_KEY_EVENT,
            rfb.Encoding.PSEUDO_FENCE,
        ])

    def test_fence_is_not_offered_by_default(self):
        """The mocked factory above answers True to every flag, so the real
        one is needed to see what is actually offered. A server sends fences
        only to a client that asked for them, and nothing here waits on one.
        """
        client = self.client
        client.factory = VNCDoToolFactory()
        client.factory.clientConnectionMade = mock.Mock()
        client._packet = bytearray(self.MSG_HANDSHAKE)
        client._handleInitial()
        client._handleServerInit(self.MSG_INIT)

        (offered,) = client.setEncodings.call_args[0]
        self.assertNotIn(rfb.Encoding.PSEUDO_FENCE, offered)

    def test_cursor_is_offered_by_default(self):
        """A server only stops painting the pointer into the framebuffer once
        a client asks for Cursor, so it is offered whether or not the shape
        will be drawn (see specs/cursor.md).
        """
        client = self.client
        client.factory = VNCDoToolFactory()
        client.factory.clientConnectionMade = mock.Mock()
        client._packet = bytearray(self.MSG_HANDSHAKE)
        client._handleInitial()
        client._handleServerInit(self.MSG_INIT)

        (offered,) = client.setEncodings.call_args[0]
        self.assertIn(rfb.Encoding.PSEUDO_CURSOR, offered)

    def test_pointer_pos_is_offered_beside_cursor(self):
        """UltraVNC revokes Cursor unless PointerPos is offered too."""
        client = self.client
        client.factory = VNCDoToolFactory()
        client.factory.clientConnectionMade = mock.Mock()
        client._packet = bytearray(self.MSG_HANDSHAKE)
        client._handleInitial()
        client._handleServerInit(self.MSG_INIT)

        (offered,) = client.setEncodings.call_args[0]
        self.assertIn(rfb.Encoding.PSEUDO_POINTER_POS, offered)

    def test_updateCursor_discards_the_shape_without_localcursor(self):
        client = self.client
        client.factory.cursor = CursorMode.OMIT
        client.screen = Image.new("RGB", (100, 100))

        client.updateCursor(0, 0, 2, 2, b"\0" * 12, b"\xc0\xc0")

        self.assertIsNone(client.cursor)

    def test_updateCursor_hides_pointer_on_zero_size(self):
        """RFC 6143 7.6.1: a Cursor pseudo-encoding update with width or
        height 0 means hide the pointer, not an empty image to decode.
        """
        client = self.client
        client.factory.cursor = CursorMode.LOCAL
        client.cursor = Image.new("RGB", (4, 4))
        client.cmask = Image.new("1", (4, 4))
        client.screen = Image.new("RGB", (100, 100))

        client.updateCursor(0, 0, 0, 0, b"", b"")

        self.assertIsNone(client.cursor)
        self.assertIsNone(client.cmask)
        client.renderScreen()

    def test_requested_encodings_replace_the_default_list(self):
        client = self.client
        client.requested_encodings = [rfb.Encoding.RAW]
        client._packet = bytearray(self.MSG_HANDSHAKE)
        client._handleInitial()
        client._handleServerInit(self.MSG_INIT)

        (offered,) = client.setEncodings.call_args[0]
        self.assertNotIn(rfb.Encoding.TIGHT, offered)
        self.assertEqual(rfb.Encoding.RAW, offered[0])

    def test_no_jpeg_quality_is_offered_by_default(self):
        """Tight is now offered by default, and a JPEG quality level is what
        tells a conforming server it may send lossy rectangles.
        """
        client = self.client
        client.factory = VNCDoToolFactory()
        client.factory.clientConnectionMade = mock.Mock()
        client._packet = bytearray(self.MSG_HANDSHAKE)
        client._handleInitial()
        client._handleServerInit(self.MSG_INIT)

        (offered,) = client.setEncodings.call_args[0]
        self.assertIn(rfb.Encoding.TIGHT, offered)
        for quality in JPEG_QUALITY_ENCODINGS:
            self.assertNotIn(quality, offered)

    def test_keyPress_single_alpha(self):
        client = self.client
        client.keyPress('a')
        client.keyEvent.assert_any_call(ord('a'), down=1)
        client.keyEvent.assert_any_call(ord('a'), down=0)

    def test_keyPress_multiple(self):
        client = self.client
        client.keyPress('ctrl-alt-del')

        # XXX doesn't ensure correct order
        client.keyEvent.assert_any_call(Key.ControlLeft, down=1)
        client.keyEvent.assert_any_call(Key.AltLeft, down=1)
        client.keyEvent.assert_any_call(Key.Delete, down=1)
        client.keyEvent.assert_any_call(Key.ControlLeft, down=0)
        client.keyEvent.assert_any_call(Key.AltLeft, down=0)
        client.keyEvent.assert_any_call(Key.Delete, down=0)

    def test_keyPress_slash_sends_forward_slash(self):
        client = self.client
        client.keyPress('slash')
        client.keyEvent.assert_any_call(Key.ForwardSlash, down=1)
        client.keyEvent.assert_any_call(Key.ForwardSlash, down=0)

    @mock.patch('vncdotool.client.Deferred')
    def test_captureScreen(self, Deferred):
        client = self.client
        client._packet = bytearray(self.MSG_HANDSHAKE)
        client._handleInitial()
        client._handleServerInit(self.MSG_INIT)
        client.vncConnectionMade()
        fname = 'foo.png'

        d = client.captureScreen(fname)
        d.addCallback.assert_called_once_with(client._captureSave, fname, None, format=None)
        assert client.framebufferUpdateRequest.called

    @mock.patch("vncdotool.client.Deferred")
    def test_captureScreen_with_format(self, Deferred):
        client = self.client
        client._packet = bytearray(self.MSG_HANDSHAKE)
        client._handleInitial()
        client._handleServerInit(self.MSG_INIT)
        client.vncConnectionMade()
        buffer = io.BytesIO()
        d = client.captureScreen(buffer, format="png")
        d.addCallback.assert_called_once_with(client._captureSave, buffer, None, format="png")
        assert client.framebufferUpdateRequest.called

    def test_captureSave(self) -> None:
        client = self.client
        client.screen = Image.new("RGB", (2, 2), "red")
        buffer = io.BytesIO()
        r = client._captureSave(None, buffer, format="PNG")
        with Image.open(buffer) as saved:
            self.assertEqual(saved.convert("RGB").getpixel((0, 0)), (255, 0, 0))
        assert r == client

    @mock.patch('PIL.Image.open')
    @mock.patch('vncdotool.client.Deferred')
    def test_expectScreen(self, Deferred, image_open):
        client = self.client
        client._packet = bytearray(self.MSG_HANDSHAKE)
        client._handleInitial()
        client._handleServerInit(self.MSG_INIT)
        client.vncConnectionMade()
        fname = 'something.png'

        region = (0, 0, 11, 22)
        Image.open.return_value.size = region[2:]

        _ = client.expectScreen(fname, 5)
        assert client.framebufferUpdateRequest.called

        image_open.assert_called_once_with(fname)

        assert client.expected_image == Image.open.return_value.convert.return_value
        Deferred.return_value.addCallback.assert_called_once_with(client._expectCompare, region, 5, 0)

    def _comparing(self, target, screen):
        client = self.client
        client.deferred = mock.Mock()
        client.framebufferUpdateRequest = mock.Mock()
        client.expected_image = target
        client.screen = screen
        return client

    def test_expectCompareSuccess(self) -> None:
        target = self._swatch((0x2A, 0x2A, 0x2A))
        client = self._comparing(target, self._swatch((0x2C, 0x2A, 0x2A)))
        result = client._expectCompare(client, (0, 0, 1, 1), 5, 0)
        assert result == client

    def test_expectCompareExactSuccess(self) -> None:
        target = self._swatch((0x2A, 0x2A, 0x2A))
        client = self._comparing(target, target.copy())
        result = client._expectCompare(client, (0, 0, 1, 1), 0, 0)
        assert result == client

    @mock.patch('vncdotool.client.Deferred')
    def test_expectCompareFails(self, Deferred):
        target = self._swatch((0x2A, 0x2A, 0x2A))
        client = self._comparing(target, self._swatch((0x2B, 0x2A, 0x2A)))

        result = client._expectCompare(client, (0, 0, 1, 1), 0, 0)

        assert result != client
        assert result == client.deferred
        assert not client.deferred.callback.called

        client.framebufferUpdateRequest.assert_called_once_with(incremental=1)
        client.deferred.addCallback.assert_called_once_with(client._expectCompare, (0, 0, 1, 1), 0, 0)

    @mock.patch('vncdotool.client.Deferred')
    def test_expectCompareMismatch(self, Deferred):
        """A target the screen is not the size of never matches, however lax
        the fuzz."""
        client = self._comparing(self._swatch((0x2A, 0x2A, 0x2A), (0x2A, 0x2A, 0x2A)),
                                 self._swatch((0x2A, 0x2A, 0x2A)))

        result = client._expectCompare(client, (0, 0, 1, 1), 255, 0)

        assert result != client
        assert result == client.deferred
        assert not client.deferred.callback.called

        client.framebufferUpdateRequest.assert_called_once_with(incremental=1)

    def test_expectCompareBlurLetsALossyFrameThrough(self):
        target = self._swatch((0x2A, 0x2A, 0x2A), (0x2A, 0x2A, 0x2A), (0x2A, 0x2A, 0x2A))
        screen = self._swatch((0x2A, 0x2A, 0x2A), (0x6A, 0x6A, 0x6A), (0x2A, 0x2A, 0x2A))
        client = self._comparing(target, screen)
        assert client._expectCompare(client, (0, 0, 3, 1), 20, 0) == client.deferred
        client.deferred = mock.Mock()
        assert client._expectCompare(client, (0, 0, 3, 1), 20, 2) == client

    def _expectAgainst(self, pixel_format, target, screen):
        client = self._comparing(target, screen)
        client.pixel_format = pixel_format
        return client._expectCompare(client, (0, 0) + target.size, client._fuzz(None), 0)

    @staticmethod
    def _swatch(*pixels):
        image = Image.new("RGB", (len(pixels), 1))
        image.putdata(pixels)
        return image

    def test_expectCompareAllowsWhatTheFormatCannotExpress(self):
        """`expect FILE` at rgb565 would otherwise poll until it timed out: no
        5-bit red can carry 0x2A, so an exact match never comes.
        """
        target = self._swatch((0x2A, 0x2A, 0x2A), (0xC1, 0xC1, 0xC1))
        screen = self._swatch((0x29, 0x29, 0x29), (0xC6, 0xC3, 0xC6))
        result = self._expectAgainst(PIXEL_FORMATS["rgb565"], target, screen)
        assert result == self.client

    def test_expectCompareStillRejectsASwappedChannel(self):
        target = self._swatch((0xB4, 0x28, 0x28))
        screen = self._swatch((0x28, 0x28, 0xB4))
        result = self._expectAgainst(PIXEL_FORMATS["rgb565"], target, screen)
        assert result == self.client.deferred

    def test_expectCompareTolerates_nothing_at_8_bits_per_channel(self):
        target = self._swatch((0x2A, 0x2A, 0x2A))
        screen = self._swatch((0x2B, 0x2A, 0x2A))
        result = self._expectAgainst(PIXEL_FORMATS["bgrx8888"], target, screen)
        assert result == self.client.deferred

    def _screenOf(self, size):
        client = self.client
        client.width, client.height = size
        client.screen = Image.new("RGB", size, (200, 100, 50))
        return client

    def _expectRegionAt(self, x, y, size=(10, 10)):
        target = Image.new("RGB", size, (1, 2, 3))
        with mock.patch("PIL.Image.open", return_value=target):
            return self.client.expectRegion("target.png", x, y)

    def test_expectRegionRejectsARegionPastTheEdge(self):
        self._screenOf((100, 100))
        with self.assertRaises(RegionError) as caught:
            self._expectRegionAt(60, 60, (100, 100))
        assert "(60, 60, 160, 160)" in str(caught.exception)
        assert "100x100" in str(caught.exception)

    def test_expectRegionRejectsANegativeOrigin(self):
        self._screenOf((100, 100))
        with self.assertRaises(RegionError):
            self._expectRegionAt(-1, 0)

    def test_expectRegionAllowsARegionFlushWithTheEdge(self):
        self._screenOf((100, 100))
        self._expectRegionAt(90, 90)

    def test_expectRegionMeasuresTheNegotiatedSizeBeforeAnyUpdateArrives(self):
        client = self.client
        client.width, client.height = 100, 100
        self._expectRegionAt(90, 90)
        with self.assertRaises(RegionError):
            self._expectRegionAt(95, 95)

    def test_expectRegionRejectsARegionADesktopResizeShrankOff(self):
        client = self._screenOf((100, 100))
        client.expected_image = Image.new("RGB", (100, 100), (1, 2, 3))
        client.updateDesktopSize(50, 50)
        with self.assertRaises(RegionError):
            client._expectCompare(client, (0, 0, 100, 100), 0, 0)

    def test_captureRegionRejectsARegionPastTheEdge(self):
        client = self._screenOf((100, 100))
        with self.assertRaises(RegionError):
            client.captureRegion(io.BytesIO(), 60, 60, 100, 100)

    def test_captureRegionRejectsANegativeOrigin(self):
        client = self._screenOf((100, 100))
        with self.assertRaises(RegionError):
            client.captureRegion(io.BytesIO(), -1, 0, 10, 10)

    def test_renderRegionCropsToTheRegion(self):
        client = self._screenOf((100, 100))
        self.assertEqual(client.renderRegion(90, 90, 10, 10).size, (10, 10))

    def test_renderRegionRejectsARegionOffTheScreen(self):
        client = self._screenOf((100, 100))
        with self.assertRaises(RegionError):
            client.renderRegion(95, 95, 10, 10)

    def test_renderScreenIsAFreshImage(self):
        """_StableWatch holds one across the updates that paste into screen."""
        client = self._screenOf((100, 100))
        self.assertIsNot(client.renderScreen(), client.screen)

    def test_captureRegionAllowsARegionFlushWithTheEdge(self):
        client = self._screenOf((100, 100))
        fp = io.BytesIO()
        client._captureSave(None, fp, (90, 90, 100, 100), format="png")
        assert Image.open(fp).size == (10, 10)

    @mock.patch('PIL.Image.frombytes')
    def test_updateRectangeFullScreen(self, frombytes):
        client = self.client
        client.image = mock.Mock()
        client.width, client.height = 100, 200
        data = mock.Mock()
        frombytes.return_value = Image.new("RGB", (100, 200), (10, 20, 30))

        client.updateRectangle(0, 0, 100, 200, data, client.pixel_format)

        Image.frombytes.assert_called_once_with('RGB', (100, 200), data, 'raw', 'RGBX')

        assert client.screen.size == (100, 200)
        assert client.screen.getpixel((0, 0)) == (10, 20, 30)

    def test_updateRectangle_first_rect_not_at_origin(self) -> None:
        client = self.client
        client._packet = bytearray(self.MSG_HANDSHAKE)
        client._handleInitial()
        client._handleServerInit(struct.pack("!HH", 300, 200) + self.MSG_INIT[4:])

        color = (200, 150, 50)
        data = (bytes(color) + b"\x00") * (10 * 10)
        client.updateRectangle(50, 30, 10, 10, data, client.pixel_format)

        assert client.screen is not None
        assert client.screen.size == (300, 200)
        assert client.screen.getpixel((50, 30)) == color
        assert client.screen.getpixel((0, 0)) == (0, 0, 0)

    @mock.patch('PIL.Image.frombytes')
    def test_updateRectangeRegion(self, frombytes):
        client = self.client
        client.image = mock.Mock()
        client.screen = mock.Mock()
        client.screen.size = (100, 100)
        data = mock.Mock()

        client.updateRectangle(20, 10, 50, 40, data, client.pixel_format)

        Image.frombytes.assert_called_once_with('RGB', (50, 40), data, 'raw', 'RGBX')

        paste = client.screen.paste
        paste.assert_called_once_with(Image.frombytes.return_value, (20, 10))

    def test_commitUpdate(self) -> None:
        rects = mock.Mock()
        self.deferred = mock.Mock()
        self.client.deferred = self.deferred
        self.client.screen = Image.new("RGB", (100, 100))
        self.client.commitUpdate(rects)

        self.deferred.callback.assert_called_once_with(self.client)

    # A framebuffer update whose only rectangle is the DesktopSize
    # pseudo-encoding carries no pixel data.
    MSG_FBU_DESKTOP_SIZE_ONLY = (
        b"\x00"  # FRAMEBUFFER_UPDATE
        b"\x00"  # padding
        b"\x00\x01"  # number-of-rectangles
        b"\x00\x00\x00\x00\x00\x04\x00\x02"  # x=0 y=0 w=4 h=2
        b"\xff\xff\xff\x21"  # PSEUDO_DESKTOP_SIZE (-223)
    )
    # The Cursor pseudo-encoding carries a cursor image and its hotspot in
    # x/y, not a region of the framebuffer.
    MSG_FBU_CURSOR_ONLY = (
        b"\x00"  # FRAMEBUFFER_UPDATE
        b"\x00"  # padding
        b"\x00\x01"  # number-of-rectangles
        b"\x00\x00\x00\x00\x00\x01\x00\x01"  # hotspot 0,0 w=1 h=1
        b"\xff\xff\xff\x11"  # PSEUDO_CURSOR (-239)
        b"\x00\x00\xff\x00"  # one RGBX pixel
        b"\x80"  # one mask row
    )
    MSG_FBU_ONE_PIXEL = (
        b"\x00"  # FRAMEBUFFER_UPDATE
        b"\x00"  # padding
        b"\x00\x01"  # number-of-rectangles
        b"\x00\x00\x00\x00\x00\x01\x00\x01"  # x=0 y=0 w=1 h=1
        b"\x00\x00\x00\x00"  # Encoding.RAW
        b"\xff\x00\x00\x00"  # one RGBX pixel
    )
    # The whole 4x2 framebuffer the DesktopSize rectangle above announces.
    MSG_FBU_WHOLE_SCREEN = (
        b"\x00"  # FRAMEBUFFER_UPDATE
        b"\x00"  # padding
        b"\x00\x01"  # number-of-rectangles
        b"\x00\x00\x00\x00\x00\x04\x00\x02"  # x=0 y=0 w=4 h=2
        b"\x00\x00\x00\x00"  # Encoding.RAW
        + b"\xff\x00\x00\x00" * 8  # eight RGBX pixels
    )

    def _connect(self) -> None:
        self.client._packet = bytearray(self.MSG_HANDSHAKE)
        self.client._handleInitial()
        self.client._handleServerInit(self.MSG_INIT)

    def test_desktop_size_only_update_rerequests_instead_of_completing(self) -> None:
        client = self.client
        self._connect()
        d = client.refreshScreen()
        fired: list = []
        d.addCallback(fired.append)
        client.framebufferUpdateRequest.reset_mock()

        client.dataReceived(self.MSG_FBU_DESKTOP_SIZE_ONLY)

        self.assertEqual(fired, [])
        client.framebufferUpdateRequest.assert_called_once_with(incremental=False)

    def test_cursor_only_update_rerequests_instead_of_completing(self) -> None:
        client = self.client
        client.factory.nocursor = False
        self._connect()
        d = client.refreshScreen()
        fired: list = []
        d.addCallback(fired.append)
        client.framebufferUpdateRequest.reset_mock()

        client.dataReceived(self.MSG_FBU_CURSOR_ONLY)

        self.assertEqual(fired, [])
        client.framebufferUpdateRequest.assert_called_once_with(incremental=False)

    MSG_FBU_EXTENDED_DESKTOP_SIZE_ONLY = (
        b"\x00"  # FRAMEBUFFER_UPDATE
        b"\x00"  # padding
        b"\x00\x01"  # number-of-rectangles
        b"\x00\x00\x00\x00\x02\x80\x01\xe0"  # reason=0 result=0 w=640 h=480
        b"\xff\xff\xfe\xcc"  # PSEUDO_EXTENDED_DESKTOP_SIZE (-308)
        b"\x01\x00\x00\x00"  # number-of-screens, padding
        b"\x00\x00\x00\x01\x00\x00\x00\x00\x02\x80\x01\xe0\x00\x00\x00\x00"
    )

    def test_extended_desktop_size_only_update_rerequests_incrementally(self) -> None:
        client = self.client
        self._connect()
        d = client.refreshScreen()
        fired: list = []
        d.addCallback(fired.append)
        client.framebufferUpdateRequest.reset_mock()

        client.dataReceived(self.MSG_FBU_EXTENDED_DESKTOP_SIZE_ONLY)

        self.assertEqual(fired, [])
        client.framebufferUpdateRequest.assert_called_once_with(incremental=True)

    def test_refresh_completes_once_pixel_data_arrives(self) -> None:
        client = self.client
        self._connect()
        d = client.refreshScreen()
        fired: list = []
        d.addCallback(fired.append)

        client.dataReceived(self.MSG_FBU_DESKTOP_SIZE_ONLY)
        client.dataReceived(self.MSG_FBU_WHOLE_SCREEN)

        self.assertEqual(fired, [client])
        assert client.screen is not None
        self.assertEqual(client.screen.size, (4, 2))
        self.assertEqual((client.width, client.height), (4, 2))

    def test_updateDesktopSize_updates_width_and_height(self) -> None:
        client = self.client
        client.width, client.height = 100, 200

        client.updateDesktopSize(300, 400)

        self.assertEqual((client.width, client.height), (300, 400))

    def test_vncRequestPassword_attribute(self):
        client = self.client
        client.sendPassword = mock.Mock()
        client.factory.password = 'mushroommushroom'
        client.vncRequestPassword()
        client.sendPassword.assert_called_once_with(client.factory.password)

    def test_vncAuthFailed_reports_connection_failed(self):
        client = self.client
        client.vncAuthFailed(b'Authentication failure')

        assert client.factory.clientConnectionFailed.called
        reason = client.factory.clientConnectionFailed.call_args[0][1]
        assert isinstance(reason.value, AuthenticationError)

    def test_vncProtocolError_reports_connection_failed(self):
        client = self.client
        client.vncProtocolError('unknown encoding received')

        assert client.factory.clientConnectionFailed.called
        reason = client.factory.clientConnectionFailed.call_args[0][1]
        assert isinstance(reason.value, ProtocolError)
        assert 'unknown encoding' in str(reason.value)


class TestVNCDoToolFactory(TestCase):

    def setUp(self) -> None:
        self.factory = VNCDoToolFactory()

    def test_init(self) -> None:
        assert self.factory.deferred

    def test_clientConnectionMade(self) -> None:
        deferred = mock.Mock()
        protocol = mock.Mock()
        self.factory.deferred = deferred

        self.factory.clientConnectionMade(protocol)

        deferred.callback.assert_called_once_with(protocol)

    def test_clientConnectionFailed(self) -> None:
        deferred = mock.Mock()
        self.factory.deferred = deferred
        reason = mock.Mock()
        connector = mock.Mock()

        self.factory.clientConnectionFailed(connector, reason)

        deferred.errback.assert_called_once_with(reason)


class TestImageMode(TestCase):

    def setUp(self) -> None:
        self.client = VNCDoToolClient()
        self.client.transport = mock.Mock()
        self.client.factory = mock.Mock()

    def patch_setPixelFormat(self) -> mock.Mock:
        """patch.object rather than assignment: it restores the method
        afterwards, and mypy does not read a bound method as assignable.
        """
        patcher = mock.patch.object(self.client, "setPixelFormat")
        self.addCleanup(patcher.stop)
        return patcher.start()

    def test_setImageMode_keeps_the_negotiated_mode(self):
        self.client.pixel_format = RGB24
        self.patch_setPixelFormat()

        self.client.setImageMode()

        assert self.client._image_mode == "RGB"

    def test_setImageMode_falls_back_when_the_server_format_cannot_be_unpacked(self):
        self.client.pixel_format = COLOUR_MAPPED
        setPixelFormat = self.patch_setPixelFormat()

        self.client.setImageMode()

        setPixelFormat.assert_called_once_with(PIXEL_FORMATS["rgbx8888"])
        assert self.client._image_mode == "RGBX"

    def test_setImageMode_keeps_a_server_format_pillow_can_unpack(self):
        self.client.pixel_format = rfb.PixelFormat(32, 24, False, True, 255, 255, 255, 24, 16, 8)
        setPixelFormat = self.patch_setPixelFormat()

        self.client.setImageMode()

        setPixelFormat.assert_not_called()
        assert self.client._image_mode == "XBGR"

    def test_setImageMode_asks_for_the_format_the_caller_requested(self):
        self.client.pixel_format = PIXEL_FORMATS["rgbx8888"]
        self.client.requested_pixel_format = PIXEL_FORMATS["rgb565"]
        setPixelFormat = self.patch_setPixelFormat()

        self.client.setImageMode()

        setPixelFormat.assert_called_once_with(PIXEL_FORMATS["rgb565"])
        assert self.client._image_mode == "BGR;16"

    def test_setImageMode_keeps_bypp_in_step_with_the_negotiated_format(self):
        # setPixelFormat is real here, not mocked like the tests above: bypp
        # is a read-through of the pixel_format it assigns, so a mock hides
        # any drift between it and the raw mode _image_mode negotiates.
        self.client.pixel_format = PIXEL_FORMATS["rgbx8888"]
        self.client.requested_pixel_format = PIXEL_FORMATS["rgb565"]

        self.client.setImageMode()

        assert self.client.bypp == PIXEL_FORMATS["rgb565"].bypp
        assert self.client._image_mode == pixelformat.raw_mode(PIXEL_FORMATS["rgb565"])

    def test_setImageMode_fails_the_connection_for_a_format_it_cannot_read(self):
        self.client.pixel_format = PIXEL_FORMATS["rgbx8888"]
        self.client.requested_pixel_format = COLOUR_MAPPED
        setPixelFormat = self.patch_setPixelFormat()

        self.client.setImageMode()

        setPixelFormat.assert_not_called()
        self.client.factory.clientConnectionFailed.assert_called_once()
        self.client.transport.loseConnection.assert_called_once()


class TestKasmVNCDialect(TestCase):

    def setUp(self) -> None:
        self.client = KasmVNCClient()
        self.client.transport = mock.Mock()

    def test_the_factory_serves_the_dialect(self) -> None:
        self.assertIs(KasmVNCFactory.protocol, KasmVNCClient)

    def test_pointer_event_carries_a_u16_mask_and_scroll_deltas(self) -> None:
        self.client.pointerEvent(20, 30, buttonmask=1)

        self.client.transport.write.assert_called_once_with(
            struct.pack("!BHHHhh", rfb.MsgC2S.POINTER_EVENT, 1, 20, 30, 0, 0)
        )

    def test_the_message_is_eleven_bytes(self) -> None:
        self.client.pointerEvent(20, 30)

        (payload,), _ = self.client.transport.write.call_args
        self.assertEqual(len(payload), 11)


class TestApplyDialect(TestCase):

    def test_standard_leaves_the_client_class_alone(self) -> None:
        factory = VNCDoToolFactory()
        apply_dialect(factory, "standard")

        self.assertIs(factory.protocol, VNCDoToolClient)

    def test_a_dialect_mixes_into_whatever_client_the_factory_uses(self) -> None:
        class CLIClient(VNCDoToolClient):
            pass

        factory = VNCDoToolFactory()
        factory.protocol = CLIClient
        apply_dialect(factory, "kasmvnc")

        self.assertTrue(issubclass(factory.protocol, KasmVNCDialect))
        self.assertTrue(issubclass(factory.protocol, CLIClient))


class TestVMWareClient(TestCase):

    def setUp(self) -> None:
        self.client = VMWareClient()
        self.client.transport = mock.Mock()
        self.client.factory = mock.Mock()
        self.client.framebufferUpdateRequest = mock.Mock()  # type: ignore[method-assign]
        self.client._handler = mock.Mock()

    def test_dataReceived_recognizes_single_pixel_update(self) -> None:
        payload = struct.pack(
            "!BxHHHHHixxxx",
            rfb.MsgS2C.FRAMEBUFFER_UPDATE,
            1,  # number-of-rectangles
            0,  # x-position
            0,  # y-position
            1,  # width
            1,  # height
            rfb.Encoding.RAW,
        )

        self.client.dataReceived(payload)

        self.client.framebufferUpdateRequest.assert_called_once_with()
        self.client._handler.assert_called_once_with()


class TestRequestedPixelFormat(TestCase):

    def test_factory_hands_its_format_to_each_client(self):
        factory = VNCDoToolFactory()
        factory.pixel_format = PIXEL_FORMATS["rgb565"]

        assert factory.buildProtocol(None).requested_pixel_format == PIXEL_FORMATS["rgb565"]

    def test_clients_ask_for_nothing_by_default(self):
        assert VNCDoToolFactory().buildProtocol(None).requested_pixel_format is None


class TestRequestedJpegQuality(TestCase):

    def test_factory_hands_its_level_to_each_client(self):
        factory = VNCDoToolFactory()
        factory.jpeg_quality = 9

        assert factory.buildProtocol(None).requested_jpeg_quality == 9

    def test_clients_offer_no_level_by_default(self):
        assert VNCDoToolFactory().buildProtocol(None).requested_jpeg_quality is None


class TestFullScreenRefresh(TestCase):
    """A non-incremental refresh waits for the whole framebuffer.

    RFC 6143 section 7.5.3 lets a server answer one request across several
    FramebufferUpdate messages.
    """

    WIDTH, HEIGHT = 8, 4

    def setUp(self) -> None:
        self.client = VNCDoToolClient()
        self.client.transport = mock.Mock()
        self.client.factory = mock.Mock()
        self.client.factory.nocursor = False
        self.client.framebufferUpdateRequest = mock.Mock()  # type: ignore[method-assign]
        self.client.setEncodings = mock.Mock()  # type: ignore[method-assign]

        self.client._packet = bytearray(TestVNCDoToolClient.MSG_HANDSHAKE)
        self.client._handleInitial()
        self.client._handleServerInit(
            struct.pack("!HH", self.WIDTH, self.HEIGHT)
            + TestVNCDoToolClient.MSG_INIT[4:]
        )

    def refresh(self, incremental: bool = False) -> list:
        outcome: list = []
        d = self.client.refreshScreen(incremental)
        d.addCallbacks(outcome.append, outcome.append)
        self.client.framebufferUpdateRequest.reset_mock()
        return outcome

    def update(self, *rects: bytes) -> None:
        self.client.dataReceived(
            struct.pack("!BxH", rfb.MsgS2C.FRAMEBUFFER_UPDATE, len(rects))
            + b"".join(rects)
        )

    @staticmethod
    def raw(x: int, y: int, width: int, height: int) -> bytes:
        return struct.pack(
            "!HHHHi", x, y, width, height, rfb.Encoding.RAW
        ) + b"\xff\x80\x00\x00" * (width * height)

    @staticmethod
    def copyrect(srcx: int, srcy: int, x: int, y: int, width: int, height: int) -> bytes:
        return struct.pack(
            "!HHHHi", x, y, width, height, rfb.Encoding.COPY_RECTANGLE
        ) + struct.pack("!HH", srcx, srcy)

    @staticmethod
    def desktop_size(width: int, height: int) -> bytes:
        return struct.pack(
            "!HHHHi", 0, 0, width, height, rfb.Encoding.PSEUDO_DESKTOP_SIZE
        )

    @staticmethod
    def cursor(width: int, height: int) -> bytes:
        return (
            struct.pack("!HHHHi", 0, 0, width, height, rfb.Encoding.PSEUDO_CURSOR)
            + b"\x00\x00\xff\x00" * (width * height)
            + b"\x80" * height
        )

    def test_a_partly_painted_framebuffer_does_not_complete_the_refresh(self) -> None:
        outcome = self.refresh()

        self.update(self.raw(0, 0, self.WIDTH, 2))

        self.assertEqual(outcome, [])
        self.client.framebufferUpdateRequest.assert_called_once_with()

    def test_the_refresh_completes_when_a_later_update_paints_the_rest(self) -> None:
        outcome = self.refresh()

        self.update(self.raw(0, 0, self.WIDTH, 2))
        self.update(self.raw(0, 2, self.WIDTH, 2))

        self.assertEqual(outcome, [self.client])

    def test_the_refresh_keeps_retrying_while_each_update_makes_progress(self) -> None:
        outcome = self.refresh()

        self.update(self.raw(0, 0, self.WIDTH, 1))
        self.update(self.raw(0, 1, self.WIDTH, 1))
        self.assertEqual(outcome, [], "gave up while the server was still making progress")

        self.update(self.raw(0, 2, self.WIDTH, 1))
        self.update(self.raw(0, 3, self.WIDTH, 1))

        self.assertEqual(outcome, [self.client])

    def test_rectangles_overlapping_do_not_add_up_to_coverage(self) -> None:
        outcome = self.refresh()

        self.update(
            self.raw(0, 0, self.WIDTH, 2), self.raw(0, 1, self.WIDTH, 2)
        )

        self.assertEqual(outcome, [])

    def test_a_copied_rectangle_counts_as_painted(self) -> None:
        outcome = self.refresh()

        self.update(self.raw(0, 0, self.WIDTH, 2))
        self.update(self.copyrect(0, 0, 0, 2, self.WIDTH, 2))

        self.assertEqual(outcome, [self.client])

    def test_a_cursor_rectangle_does_not_count_as_painted(self) -> None:
        outcome = self.refresh()
        self.update(self.raw(0, 0, self.WIDTH, 2))

        with self.assertLogs("vncdotool.client", "WARNING") as logs:
            self.update(self.cursor(2, 2))

        self.assertEqual(outcome, [self.client])
        self.assertIn("16 of the 8x4 framebuffer unpainted", logs.output[0])

    def test_pseudo_rectangles_alone_do_not_complete_an_unpainted_refresh(self) -> None:
        """TightVNC answers the first request on a fresh connection this way."""
        outcome = self.refresh()

        self.update(self.desktop_size(self.WIDTH, self.HEIGHT), self.cursor(2, 2))
        self.update(self.cursor(2, 2))

        self.assertEqual(outcome, [], "completed on a framebuffer nothing painted")
        self.assertEqual(self.client.framebufferUpdateRequest.call_count, 2)

    def test_the_refresh_completes_once_the_paint_follows_the_pseudo_rectangles(self) -> None:
        outcome = self.refresh()

        self.update(self.desktop_size(self.WIDTH, self.HEIGHT), self.cursor(2, 2))
        self.update(self.raw(0, 0, self.WIDTH, self.HEIGHT))

        self.assertEqual(outcome, [self.client])

    def test_an_incremental_refresh_completes_on_the_first_change(self) -> None:
        outcome = self.refresh(incremental=True)

        self.update(self.raw(0, 0, 1, 1))

        self.assertEqual(outcome, [self.client])

    def test_a_server_that_stays_short_completes_the_refresh_anyway(self) -> None:
        outcome = self.refresh()

        self.update(self.raw(0, 0, self.WIDTH, 2))
        self.assertEqual(outcome, [], "gave up without re-requesting")

        with self.assertLogs("vncdotool.client", "WARNING") as logs:
            self.update(self.raw(0, 0, self.WIDTH, 2))

        self.assertEqual(outcome, [self.client])
        self.assertIn("16 of the 8x4 framebuffer unpainted", logs.output[0])

    def test_a_short_answer_is_re_requested_before_it_is_given_up_on(self) -> None:
        self.refresh()

        self.update(self.raw(0, 0, self.WIDTH, 2))

        self.client.framebufferUpdateRequest.assert_called_once_with()

    def test_a_covered_framebuffer_warns_about_nothing(self) -> None:
        outcome = self.refresh()

        with mock.patch.object(log, "warning") as warned:
            self.update(self.raw(0, 0, self.WIDTH, self.HEIGHT))

        self.assertEqual(outcome, [self.client])
        warned.assert_not_called()


class TestStableScreen(TestCase):
    """`stable` waits out a window in which nothing changed.

    A `Clock` stands in for the reactor so the window can be advanced without
    running one.
    """

    def setUp(self) -> None:
        self.clock = Clock()
        patcher = mock.patch("vncdotool.client.reactor", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.client = VNCDoToolClient()
        self.client.transport = mock.Mock()
        self.client.factory = mock.Mock()
        self.client.framebufferUpdateRequest = mock.Mock()  # type: ignore[method-assign]
        self.client.screen = Image.new("RGB", (4, 4), "black")

    def waitStable(self, seconds, fuzz, region=None):
        d = (
            self.client.stableRegion(seconds, *region, fuzz)
            if region
            else self.client.stableScreen(seconds, fuzz)
        )
        settled: list = []
        d.addCallback(settled.append)
        return settled

    def paint(self, colour, at=(0, 0), size=(4, 4)) -> None:
        assert self.client.screen is not None
        self.client.screen.paste(Image.new("RGB", size, colour), at)
        self.client.commitUpdate([(at[0], at[1], size[0], size[1])])

    def test_settles_once_the_window_passes_with_no_change(self) -> None:
        settled = self.waitStable(1.5, 0)

        self.clock.advance(1.4)
        assert settled == []

        self.clock.advance(0.2)
        assert settled == [self.client]

    def test_a_change_restarts_the_window(self) -> None:
        settled = self.waitStable(1.0, 0)

        self.clock.advance(0.9)
        self.paint("white")
        self.clock.advance(0.9)
        assert settled == []

        self.clock.advance(0.2)
        assert settled == [self.client]

    def test_a_repaint_within_the_fuzz_does_not_restart_the_window(self) -> None:
        settled = self.waitStable(1.0, 20)

        self.clock.advance(0.9)
        self.paint((5, 5, 5))
        self.clock.advance(0.2)

        assert settled == [self.client]

    def test_keeps_a_request_outstanding_while_it_waits(self) -> None:
        self.waitStable(1.0, 0)
        self.client.framebufferUpdateRequest.reset_mock()

        self.paint("white")

        self.client.framebufferUpdateRequest.assert_called_once_with(incremental=True)

    def test_asks_for_a_whole_screen_when_it_has_no_baseline(self) -> None:
        self.client.screen = None

        self.waitStable(1.0, 0)

        self.client.framebufferUpdateRequest.assert_called_once_with(incremental=False)
        assert not self.clock.getDelayedCalls()

    def test_starts_the_window_once_a_first_frame_arrives(self) -> None:
        self.client.screen = None
        settled = self.waitStable(1.0, 0)

        self.client.screen = Image.new("RGB", (4, 4), "black")
        self.client.commitUpdate([(0, 0, 4, 4)])
        self.clock.advance(1.1)

        assert settled == [self.client]

    def test_stops_requesting_once_it_has_settled(self) -> None:
        self.waitStable(1.0, 0)
        self.clock.advance(1.1)
        self.client.framebufferUpdateRequest.reset_mock()

        self.paint("white")

        assert not self.client.framebufferUpdateRequest.called

    def test_a_region_ignores_a_change_outside_it(self) -> None:
        self.client.screen = Image.new("RGB", (8, 8), "black")
        settled = self.waitStable(1.0, 0, region=(0, 0, 4, 4))

        self.clock.advance(0.9)
        self.paint("white", at=(4, 4))
        self.clock.advance(0.2)

        assert settled == [self.client]

    def test_a_region_sees_a_change_inside_it(self) -> None:
        self.client.screen = Image.new("RGB", (8, 8), "black")
        settled = self.waitStable(1.0, 0, region=(0, 0, 4, 4))

        self.clock.advance(0.9)
        self.paint("white", at=(0, 0))
        self.clock.advance(0.2)

        assert settled == []


class TestResize(TestCase):
    """`resize` sends SetDesktopSize and reports what the server answered.

    A `Clock` stands in for the reactor so tests can assert nothing gets
    scheduled on it.
    """

    SCREEN = rfb.Screen(0x6B8B4567, 0, 0, 256, 192, 0)

    def setUp(self) -> None:
        self.clock = Clock()
        patcher = mock.patch("vncdotool.client.reactor", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.client = VNCDoToolClient()
        self.client.transport = mock.Mock()
        self.client.factory = mock.Mock()
        self.client.framebufferUpdateRequest = mock.Mock()  # type: ignore[method-assign]
        self.client.width, self.client.height = 256, 192

    def advertise(self) -> None:
        self.client.negotiated_encodings.add(
            rfb.Encoding.PSEUDO_EXTENDED_DESKTOP_SIZE
        )
        self.client.screens = (self.SCREEN,)

    def answer(self, result, width=320, height=240):
        self.client.updateExtendedDesktopSize(
            rfb.DesktopSizeReason.THIS_CLIENT,
            result,
            width,
            height,
            [rfb.Screen(0x6B8B4567, 0, 0, width, height, 0)],
        )

    def outcome(self, d):
        fired: list = []
        d.addBoth(fired.append)
        return fired

    def test_a_granted_resize_fires_the_result(self) -> None:
        self.advertise()
        fired = self.outcome(self.client.resizeScreen(320, 240))

        self.assertEqual(fired, [])
        self.answer(rfb.DesktopSizeResult.SUCCESS)

        self.assertEqual(fired, [self.client])
        self.assertEqual(self.clock.getDelayedCalls(), [])

    def test_the_request_carries_the_advertised_screen_id(self) -> None:
        """Wire serialization of `Screen` is test_rfb.py's job; this is
        about `_sendResize` building the right one -- the advertised id
        preserved, x/y zeroed, the new size in place of the old.
        """
        self.advertise()
        self.client.setDesktopSize = mock.Mock()  # type: ignore[method-assign]

        self.client.resizeScreen(320, 240)

        self.client.setDesktopSize.assert_called_once_with(
            320, 240, [rfb.Screen(0x6B8B4567, 0, 0, 320, 240, 0)]
        )
        self.client.framebufferUpdateRequest.assert_called_once_with(incremental=True)

    def test_a_refused_resize_fails_rather_than_going_quiet(self) -> None:
        self.advertise()
        fired = self.outcome(self.client.resizeScreen(320, 240))

        self.answer(rfb.DesktopSizeResult.PROHIBITED)

        (failure,) = fired
        self.assertIsInstance(failure.value, DesktopResizeError)
        self.assertIn("PROHIBITED", str(failure.value))

    def test_an_unadvertised_server_is_asked_before_being_told(self) -> None:
        fired = self.outcome(self.client.resizeScreen(320, 240))

        self.client.framebufferUpdateRequest.assert_called_once_with(incremental=False)
        self.client.transport.write.assert_not_called()

        self.client.updateExtendedDesktopSize(
            rfb.DesktopSizeReason.SERVER,
            rfb.DesktopSizeResult.SUCCESS,
            256,
            192,
            [self.SCREEN],
        )
        self.client.transport.write.assert_called_once()

        self.answer(rfb.DesktopSizeResult.SUCCESS)
        self.assertEqual(fired, [self.client])

    def test_repeated_server_rectangles_send_one_request(self) -> None:
        """TigerVNC sends three server-reason rectangles before the answer to
        a request of ours.
        """
        self.client.resizeScreen(320, 240)
        for _ in range(3):
            self.client.updateExtendedDesktopSize(
                rfb.DesktopSizeReason.SERVER,
                rfb.DesktopSizeResult.SUCCESS,
                256,
                192,
                [self.SCREEN],
            )

        self.client.transport.write.assert_called_once()

    def test_a_silent_server_is_left_pending_not_timed_out(self) -> None:
        """No command in this file manufactures its own deadline; a server
        that never answers leaves the Deferred unfired, same as
        `captureScreen`/`expectScreen`/`stableScreen`/`refreshScreen` do.
        """
        fired = self.outcome(self.client.resizeScreen(320, 240))

        self.assertEqual(self.clock.getDelayedCalls(), [])
        self.clock.advance(10_000)

        self.assertEqual(fired, [])

    def test_the_size_already_in_force_sends_nothing(self) -> None:
        self.advertise()
        fired = self.outcome(self.client.resizeScreen(256, 192))

        self.assertEqual(fired, [self.client])
        self.client.transport.write.assert_not_called()
        self.assertEqual(self.clock.getDelayedCalls(), [])

    def test_a_lost_connection_fails_a_pending_resize(self) -> None:
        self.advertise()
        fired = self.outcome(self.client.resizeScreen(320, 240))

        self.client.connectionLost(mock.Mock())

        (failure,) = fired
        self.assertIsInstance(failure.value, DesktopResizeError)


def _connected(jpeg_quality):
    client = VNCDoToolClient()
    client.transport = mock.Mock()
    client.factory = mock.Mock()
    for flag in ("pseudodesktop", "last_rect", "qemu_extended_key"):
        setattr(client.factory, flag, False)
    client.factory.cursor = CursorMode.OMIT
    client.setEncodings = mock.Mock()
    client.requested_jpeg_quality = jpeg_quality
    client.vncConnectionMade()
    return client.setEncodings.call_args.args[0]


class TestJpegQualityIsOptional(TestCase):

    def test_no_level_offers_no_pseudo_encoding(self):
        offered = _connected(None)

        assert not [enc for enc in offered if -32 <= enc <= -23]


class JpegQualityLevel:
    level: int

    def test_offers_the_pseudo_encoding_that_carries_it(self) -> None:
        # Level 0 is -32 (low) up to level 9 at -23 (specs/tight-wire.md section 8).
        offered = _connected(self.level)

        assert offered[-1] == -32 + self.level  # type: ignore[attr-defined]


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTests(tests)
    for level in range(len(JPEG_QUALITY_ENCODINGS)):
        name = f"TestJpegQualityLevel_{level}"
        case = type(name, (JpegQualityLevel, TestCase), {"level": level})
        suite.addTest(case("test_offers_the_pseudo_encoding_that_carries_it"))
    return suite
