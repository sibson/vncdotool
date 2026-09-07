from unittest import TestCase, mock
import io
import struct
import unittest

from PIL import Image
from twisted.internet.task import Clock

from vncdotool import client, pixelformat, rfb
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
        self.client = client.VNCDoToolClient()
        self.client.transport = mock.Mock()
        self.client.factory = mock.Mock()

        self.client.framebufferUpdateRequest = mock.Mock()  # type: ignore[method-assign]
        self.client.pointerEvent = mock.Mock()  # type: ignore[method-assign]
        self.client.keyEvent = mock.Mock()  # type: ignore[method-assign]
        self.client.setEncodings = mock.Mock()  # type: ignore[method-assign]

    def test_vncConnectionMade(self):
        cli = self.client
        cli._packet = bytearray(self.MSG_HANDSHAKE)
        cli._handleInitial()
        cli._handleServerInit(self.MSG_INIT)
        factory = cli.factory
        factory.clientConnectionMade.assert_called_once_with(cli)
        self.client.setEncodings.assert_called_once_with([
            client.rfb.Encoding.TIGHT,
            client.rfb.Encoding.HEXTILE,
            client.rfb.Encoding.RAW,
            client.rfb.Encoding.PSEUDO_CURSOR,
            client.rfb.Encoding.PSEUDO_DESKTOP_SIZE,
            client.rfb.Encoding.PSEUDO_EXTENDED_DESKTOP_SIZE,
            client.rfb.Encoding.PSEUDO_LAST_RECT,
            client.rfb.Encoding.PSEUDO_QEMU_EXTENDED_KEY_EVENT,
            client.rfb.Encoding.PSEUDO_FENCE,
        ])

    def test_fence_is_not_offered_by_default(self):
        """The mocked factory above answers True to every flag, so the real
        one is needed to see what is actually offered. A server sends fences
        only to a client that asked for them, and nothing here waits on one.
        """
        cli = self.client
        cli.factory = client.VNCDoToolFactory()
        cli.factory.clientConnectionMade = mock.Mock()
        cli._packet = bytearray(self.MSG_HANDSHAKE)
        cli._handleInitial()
        cli._handleServerInit(self.MSG_INIT)

        (offered,) = cli.setEncodings.call_args[0]
        self.assertNotIn(client.rfb.Encoding.PSEUDO_FENCE, offered)

    def test_updateCursor_hides_pointer_on_zero_size(self):
        """RFC 6143 7.6.1: a Cursor pseudo-encoding update with width or
        height 0 means hide the pointer, not an empty image to decode.
        """
        cli = self.client
        cli.factory.nocursor = False
        cli.cursor = Image.new("RGB", (4, 4))
        cli.cmask = Image.new("1", (4, 4))
        cli.screen = Image.new("RGB", (100, 100))

        cli.updateCursor(0, 0, 0, 0, b"", b"")

        self.assertIsNone(cli.cursor)
        self.assertIsNone(cli.cmask)
        cli.drawCursor()

    def test_requested_encodings_replace_the_default_list(self):
        cli = self.client
        cli.requested_encodings = [client.rfb.Encoding.RAW]
        cli._packet = bytearray(self.MSG_HANDSHAKE)
        cli._handleInitial()
        cli._handleServerInit(self.MSG_INIT)

        (offered,) = cli.setEncodings.call_args[0]
        self.assertNotIn(client.rfb.Encoding.TIGHT, offered)
        self.assertEqual(client.rfb.Encoding.RAW, offered[0])

    def test_no_jpeg_quality_is_offered_by_default(self):
        """Tight is now offered by default, and a JPEG quality level is what
        tells a conforming server it may send lossy rectangles.
        """
        cli = self.client
        cli.factory = client.VNCDoToolFactory()
        cli.factory.clientConnectionMade = mock.Mock()
        cli._packet = bytearray(self.MSG_HANDSHAKE)
        cli._handleInitial()
        cli._handleServerInit(self.MSG_INIT)

        (offered,) = cli.setEncodings.call_args[0]
        self.assertIn(client.rfb.Encoding.TIGHT, offered)
        for quality in client.JPEG_QUALITY_ENCODINGS:
            self.assertNotIn(quality, offered)

    def test_keyPress_single_alpha(self):
        cli = self.client
        cli.keyPress('a')
        cli.keyEvent.assert_any_call(ord('a'), down=1)
        cli.keyEvent.assert_any_call(ord('a'), down=0)

    def test_keyPress_multiple(self):
        cli = self.client
        cli.keyPress('ctrl-alt-del')

        # XXX doesn't ensure correct order
        cli.keyEvent.assert_any_call(Key.ControlLeft, down=1)
        cli.keyEvent.assert_any_call(Key.AltLeft, down=1)
        cli.keyEvent.assert_any_call(Key.Delete, down=1)
        cli.keyEvent.assert_any_call(Key.ControlLeft, down=0)
        cli.keyEvent.assert_any_call(Key.AltLeft, down=0)
        cli.keyEvent.assert_any_call(Key.Delete, down=0)

    @mock.patch('vncdotool.client.Deferred')
    def test_captureScreen(self, Deferred):
        cli = self.client
        cli._packet = bytearray(self.MSG_HANDSHAKE)
        cli._handleInitial()
        cli._handleServerInit(self.MSG_INIT)
        cli.vncConnectionMade()
        fname = 'foo.png'

        d = cli.captureScreen(fname)
        d.addCallback.assert_called_once_with(cli._captureSave, fname)
        assert cli.framebufferUpdateRequest.called

    @mock.patch("vncdotool.client.Deferred")
    def test_captureScreen_with_format(self, Deferred):
        cli = self.client
        cli._packet = bytearray(self.MSG_HANDSHAKE)
        cli._handleInitial()
        cli._handleServerInit(self.MSG_INIT)
        cli.vncConnectionMade()
        buffer = io.BytesIO()
        d = cli.captureScreen(buffer, format="png")
        d.addCallback.assert_called_once_with(cli._captureSave, buffer, format="png")
        assert cli.framebufferUpdateRequest.called

    def test_captureSave(self) -> None:
        cli = self.client
        cli.screen = mock.Mock()
        fname = 'foo.png'
        r = cli._captureSave(cli.screen, fname)
        cli.screen.save.assert_called_once_with(fname, format=None)
        assert r == cli

    @mock.patch('PIL.Image.open')
    @mock.patch('vncdotool.client.Deferred')
    def test_expectScreen(self, Deferred, image_open):
        cli = self.client
        cli._packet = bytearray(self.MSG_HANDSHAKE)
        cli._handleInitial()
        cli._handleServerInit(self.MSG_INIT)
        cli.vncConnectionMade()
        fname = 'something.png'

        region = (0, 0, 11, 22)
        client.Image.open.return_value.size = region[2:]

        _ = cli.expectScreen(fname, 5)
        assert cli.framebufferUpdateRequest.called

        image_open.assert_called_once_with(fname)

        assert cli.expected_image == client.Image.open.return_value.convert.return_value
        Deferred.return_value.addCallback.assert_called_once_with(cli._expectCompare, region, 5, 0)

    def _comparing(self, target, screen):
        cli = self.client
        cli.deferred = mock.Mock()
        cli.framebufferUpdateRequest = mock.Mock()
        cli.expected_image = target
        cli.screen = screen
        return cli

    def test_expectCompareSuccess(self) -> None:
        target = self._swatch((0x2A, 0x2A, 0x2A))
        cli = self._comparing(target, self._swatch((0x2C, 0x2A, 0x2A)))
        result = cli._expectCompare(cli, (0, 0, 1, 1), 5, 0)
        assert result == cli

    def test_expectCompareExactSuccess(self) -> None:
        target = self._swatch((0x2A, 0x2A, 0x2A))
        cli = self._comparing(target, target.copy())
        result = cli._expectCompare(cli, (0, 0, 1, 1), 0, 0)
        assert result == cli

    @mock.patch('vncdotool.client.Deferred')
    def test_expectCompareFails(self, Deferred):
        target = self._swatch((0x2A, 0x2A, 0x2A))
        cli = self._comparing(target, self._swatch((0x2B, 0x2A, 0x2A)))

        result = cli._expectCompare(cli, (0, 0, 1, 1), 0, 0)

        assert result != cli
        assert result == cli.deferred
        assert not cli.deferred.callback.called

        cli.framebufferUpdateRequest.assert_called_once_with(incremental=1)
        cli.deferred.addCallback.assert_called_once_with(cli._expectCompare, (0, 0, 1, 1), 0, 0)

    @mock.patch('vncdotool.client.Deferred')
    def test_expectCompareMismatch(self, Deferred):
        """A target the screen is not the size of never matches, however lax
        the fuzz."""
        cli = self._comparing(self._swatch((0x2A, 0x2A, 0x2A), (0x2A, 0x2A, 0x2A)),
                              self._swatch((0x2A, 0x2A, 0x2A)))

        result = cli._expectCompare(cli, (0, 0, 1, 1), 255, 0)

        assert result != cli
        assert result == cli.deferred
        assert not cli.deferred.callback.called

        cli.framebufferUpdateRequest.assert_called_once_with(incremental=1)

    def test_expectCompareBlurLetsALossyFrameThrough(self):
        target = self._swatch((0x2A, 0x2A, 0x2A), (0x2A, 0x2A, 0x2A), (0x2A, 0x2A, 0x2A))
        screen = self._swatch((0x2A, 0x2A, 0x2A), (0x6A, 0x6A, 0x6A), (0x2A, 0x2A, 0x2A))
        cli = self._comparing(target, screen)
        assert cli._expectCompare(cli, (0, 0, 3, 1), 20, 0) == cli.deferred
        cli.deferred = mock.Mock()
        assert cli._expectCompare(cli, (0, 0, 3, 1), 20, 2) == cli

    def _expectAgainst(self, pixel_format, target, screen):
        cli = self._comparing(target, screen)
        cli.pixel_format = pixel_format
        return cli._expectCompare(cli, (0, 0) + target.size, cli._fuzz(None), 0)

    @staticmethod
    def _swatch(*pixels):
        image = client.Image.new("RGB", (len(pixels), 1))
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
        cli = self.client
        cli.width, cli.height = size
        cli.screen = client.Image.new("RGB", size, (200, 100, 50))
        return cli

    def _expectRegionAt(self, x, y, size=(10, 10)):
        target = client.Image.new("RGB", size, (1, 2, 3))
        with mock.patch("PIL.Image.open", return_value=target):
            return self.client.expectRegion("target.png", x, y)

    def test_expectRegionRejectsARegionPastTheEdge(self):
        self._screenOf((100, 100))
        with self.assertRaises(client.RegionError) as caught:
            self._expectRegionAt(60, 60, (100, 100))
        assert "(60, 60, 160, 160)" in str(caught.exception)
        assert "100x100" in str(caught.exception)

    def test_expectRegionRejectsANegativeOrigin(self):
        self._screenOf((100, 100))
        with self.assertRaises(client.RegionError):
            self._expectRegionAt(-1, 0)

    def test_expectRegionAllowsARegionFlushWithTheEdge(self):
        self._screenOf((100, 100))
        self._expectRegionAt(90, 90)

    def test_expectRegionMeasuresTheNegotiatedSizeBeforeAnyUpdateArrives(self):
        cli = self.client
        cli.width, cli.height = 100, 100
        self._expectRegionAt(90, 90)
        with self.assertRaises(client.RegionError):
            self._expectRegionAt(95, 95)

    def test_expectRegionRejectsARegionADesktopResizeShrankOff(self):
        cli = self._screenOf((100, 100))
        cli.expected_image = client.Image.new("RGB", (100, 100), (1, 2, 3))
        cli.updateDesktopSize(50, 50)
        with self.assertRaises(client.RegionError):
            cli._expectCompare(cli, (0, 0, 100, 100), 0, 0)

    def test_captureRegionRejectsARegionPastTheEdge(self):
        cli = self._screenOf((100, 100))
        with self.assertRaises(client.RegionError):
            cli.captureRegion(io.BytesIO(), 60, 60, 100, 100)

    def test_captureRegionRejectsANegativeOrigin(self):
        cli = self._screenOf((100, 100))
        with self.assertRaises(client.RegionError):
            cli.captureRegion(io.BytesIO(), -1, 0, 10, 10)

    def test_captureRegionAllowsARegionFlushWithTheEdge(self):
        cli = self._screenOf((100, 100))
        fp = io.BytesIO()
        cli._captureSave(None, fp, 90, 90, 100, 100, format="png")
        assert client.Image.open(fp).size == (10, 10)

    @mock.patch('PIL.Image.frombytes')
    def test_updateRectangeFullScreen(self, frombytes):
        cli = self.client
        cli.image = mock.Mock()
        cli.width, cli.height = 100, 200
        data = mock.Mock()
        frombytes.return_value = client.Image.new("RGB", (100, 200), (10, 20, 30))

        cli.updateRectangle(0, 0, 100, 200, data, cli.pixel_format)

        client.Image.frombytes.assert_called_once_with('RGB', (100, 200), data, 'raw', 'RGBX')

        assert cli.screen.size == (100, 200)
        assert cli.screen.getpixel((0, 0)) == (10, 20, 30)

    def test_updateRectangle_first_rect_not_at_origin(self) -> None:
        cli = self.client
        cli._packet = bytearray(self.MSG_HANDSHAKE)
        cli._handleInitial()
        cli._handleServerInit(struct.pack("!HH", 300, 200) + self.MSG_INIT[4:])

        color = (200, 150, 50)
        data = (bytes(color) + b"\x00") * (10 * 10)
        cli.updateRectangle(50, 30, 10, 10, data, cli.pixel_format)

        assert cli.screen is not None
        assert cli.screen.size == (300, 200)
        assert cli.screen.getpixel((50, 30)) == color
        assert cli.screen.getpixel((0, 0)) == (0, 0, 0)

    @mock.patch('PIL.Image.frombytes')
    def test_updateRectangeRegion(self, frombytes):
        cli = self.client
        cli.image = mock.Mock()
        cli.screen = mock.Mock()
        cli.screen.size = (100, 100)
        data = mock.Mock()

        cli.updateRectangle(20, 10, 50, 40, data, cli.pixel_format)

        client.Image.frombytes.assert_called_once_with('RGB', (50, 40), data, 'raw', 'RGBX')

        paste = cli.screen.paste
        paste.assert_called_once_with(client.Image.frombytes.return_value, (20, 10))

    def test_commitUpdate(self) -> None:
        rects = mock.Mock()
        self.deferred = mock.Mock()
        self.client.deferred = self.deferred
        self.client.commitUpdate(rects)

        self.deferred.callback.assert_called_once_with(self.client)

    # A framebuffer update whose only rectangle is the DesktopSize
    # pseudo-encoding carries no pixel data.
    MSG_FBU_DESKTOP_SIZE_ONLY = (
        b"\x00"  # FRAMEBUFFER_UPDATE
        b"\x00"  # padding
        b"\x00\x01"  # number-of-rectangles
        b"\x00\x00\x00\x00\x07\x80\x04\xb0"  # x=0 y=0 w=1920 h=1200
        b"\xff\xff\xff\x21"  # PSEUDO_DESKTOP_SIZE (-223)
    )
    MSG_FBU_ONE_PIXEL = (
        b"\x00"  # FRAMEBUFFER_UPDATE
        b"\x00"  # padding
        b"\x00\x01"  # number-of-rectangles
        b"\x00\x00\x00\x00\x00\x01\x00\x01"  # x=0 y=0 w=1 h=1
        b"\x00\x00\x00\x00"  # Encoding.RAW
        b"\xff\x00\x00\x00"  # one RGBX pixel
    )

    def _connect(self) -> None:
        self.client._packet = bytearray(self.MSG_HANDSHAKE)
        self.client._handleInitial()
        self.client._handleServerInit(self.MSG_INIT)

    def test_desktop_size_only_update_rerequests_instead_of_completing(self) -> None:
        cli = self.client
        self._connect()
        d = cli.refreshScreen()
        fired: list = []
        d.addCallback(fired.append)
        cli.framebufferUpdateRequest.reset_mock()

        cli.dataReceived(self.MSG_FBU_DESKTOP_SIZE_ONLY)

        self.assertEqual(fired, [])
        cli.framebufferUpdateRequest.assert_called_once_with(incremental=False)

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
        cli = self.client
        self._connect()
        d = cli.refreshScreen()
        fired: list = []
        d.addCallback(fired.append)
        cli.framebufferUpdateRequest.reset_mock()

        cli.dataReceived(self.MSG_FBU_EXTENDED_DESKTOP_SIZE_ONLY)

        self.assertEqual(fired, [])
        cli.framebufferUpdateRequest.assert_called_once_with(incremental=True)

    def test_refresh_completes_once_pixel_data_arrives(self) -> None:
        cli = self.client
        self._connect()
        d = cli.refreshScreen()
        fired: list = []
        d.addCallback(fired.append)

        cli.dataReceived(self.MSG_FBU_DESKTOP_SIZE_ONLY)
        cli.dataReceived(self.MSG_FBU_ONE_PIXEL)

        self.assertEqual(fired, [cli])
        assert cli.screen is not None
        self.assertEqual(cli.screen.size, (1920, 1200))
        self.assertEqual((cli.width, cli.height), (1920, 1200))

    def test_updateDesktopSize_updates_width_and_height(self) -> None:
        cli = self.client
        cli.width, cli.height = 100, 200

        cli.updateDesktopSize(300, 400)

        self.assertEqual((cli.width, cli.height), (300, 400))

    def test_vncRequestPassword_attribute(self):
        cli = self.client
        cli.sendPassword = mock.Mock()
        cli.factory.password = 'mushroommushroom'
        cli.vncRequestPassword()
        cli.sendPassword.assert_called_once_with(cli.factory.password)

    def test_vncAuthFailed_reports_connection_failed(self):
        cli = self.client
        cli.vncAuthFailed(b'Authentication failure')

        assert cli.factory.clientConnectionFailed.called
        reason = cli.factory.clientConnectionFailed.call_args[0][1]
        assert isinstance(reason.value, client.AuthenticationError)

    def test_vncProtocolError_reports_connection_failed(self):
        cli = self.client
        cli.vncProtocolError('unknown encoding received')

        assert cli.factory.clientConnectionFailed.called
        reason = cli.factory.clientConnectionFailed.call_args[0][1]
        assert isinstance(reason.value, client.ProtocolError)
        assert 'unknown encoding' in str(reason.value)


class TestVNCDoToolFactory(TestCase):

    def setUp(self) -> None:
        self.factory = client.VNCDoToolFactory()

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
        self.client = client.VNCDoToolClient()
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


class TestVMWareClient(TestCase):

    def setUp(self) -> None:
        self.client = client.VMWareClient()
        self.client.transport = mock.Mock()
        self.client.factory = mock.Mock()
        self.client.framebufferUpdateRequest = mock.Mock()  # type: ignore[method-assign]
        self.client._handler = mock.Mock()

    def test_dataReceived_recognizes_single_pixel_update(self) -> None:
        payload = struct.pack(
            "!BxHHHHHixxxx",
            client.rfb.MsgS2C.FRAMEBUFFER_UPDATE,
            1,  # number-of-rectangles
            0,  # x-position
            0,  # y-position
            1,  # width
            1,  # height
            client.rfb.Encoding.RAW,
        )

        self.client.dataReceived(payload)

        self.client.framebufferUpdateRequest.assert_called_once_with()
        self.client._handler.assert_called_once_with()


class TestRequestedPixelFormat(TestCase):

    def test_factory_hands_its_format_to_each_client(self):
        factory = client.VNCDoToolFactory()
        factory.pixel_format = PIXEL_FORMATS["rgb565"]

        assert factory.buildProtocol(None).requested_pixel_format == PIXEL_FORMATS["rgb565"]

    def test_clients_ask_for_nothing_by_default(self):
        assert client.VNCDoToolFactory().buildProtocol(None).requested_pixel_format is None


class TestRequestedJpegQuality(TestCase):

    def test_factory_hands_its_level_to_each_client(self):
        factory = client.VNCDoToolFactory()
        factory.jpeg_quality = 9

        assert factory.buildProtocol(None).requested_jpeg_quality == 9

    def test_clients_offer_no_level_by_default(self):
        assert client.VNCDoToolFactory().buildProtocol(None).requested_jpeg_quality is None


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

        self.client = client.VNCDoToolClient()
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

    A `Clock` stands in for the reactor so the answer-timeout can be advanced
    without running one.
    """

    SCREEN = rfb.Screen(0x6B8B4567, 0, 0, 256, 192, 0)

    def setUp(self) -> None:
        self.clock = Clock()
        patcher = mock.patch("vncdotool.client.reactor", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.client = client.VNCDoToolClient()
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
        fired = self.outcome(self.client.resize(320, 240))

        self.assertEqual(fired, [])
        self.answer(rfb.DesktopSizeResult.SUCCESS)

        self.assertEqual(fired, [self.client])
        self.assertEqual(self.clock.getDelayedCalls(), [])

    def test_the_request_carries_the_advertised_screen_id(self) -> None:
        self.advertise()
        self.client.resize(320, 240)

        self.client.transport.write.assert_called_once_with(
            b"\xfb\x00\x01\x40\x00\xf0\x01\x00"
            b"\x6b\x8b\x45\x67\x00\x00\x00\x00\x01\x40\x00\xf0\x00\x00\x00\x00"
        )
        self.client.framebufferUpdateRequest.assert_called_once_with(incremental=True)

    def test_a_refused_resize_fails_rather_than_going_quiet(self) -> None:
        self.advertise()
        fired = self.outcome(self.client.resize(320, 240))

        self.answer(rfb.DesktopSizeResult.PROHIBITED)

        (failure,) = fired
        self.assertIsInstance(failure.value, client.DesktopResizeError)
        self.assertIn("PROHIBITED", str(failure.value))

    def test_an_unadvertised_server_is_asked_before_being_told(self) -> None:
        fired = self.outcome(self.client.resize(320, 240))

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
        self.client.resize(320, 240)
        for _ in range(3):
            self.client.updateExtendedDesktopSize(
                rfb.DesktopSizeReason.SERVER,
                rfb.DesktopSizeResult.SUCCESS,
                256,
                192,
                [self.SCREEN],
            )

        self.client.transport.write.assert_called_once()

    def test_a_silent_server_fails_rather_than_hanging(self) -> None:
        fired = self.outcome(self.client.resize(320, 240))

        self.clock.advance(self.client.RESIZE_TIMEOUT + 1)

        (failure,) = fired
        self.assertIsInstance(failure.value, client.DesktopResizeError)

    def test_the_size_already_in_force_sends_nothing(self) -> None:
        self.advertise()
        fired = self.outcome(self.client.resize(256, 192))

        self.assertEqual(fired, [self.client])
        self.client.transport.write.assert_not_called()
        self.assertEqual(self.clock.getDelayedCalls(), [])

    def test_a_lost_connection_fails_a_pending_resize(self) -> None:
        self.advertise()
        fired = self.outcome(self.client.resize(320, 240))

        self.client.connectionLost(mock.Mock())

        (failure,) = fired
        self.assertIsInstance(failure.value, client.DesktopResizeError)


def _connected(jpeg_quality):
    cli = client.VNCDoToolClient()
    cli.transport = mock.Mock()
    cli.factory = mock.Mock()
    for flag in ("pseudocursor", "nocursor", "pseudodesktop", "last_rect", "qemu_extended_key"):
        setattr(cli.factory, flag, False)
    cli.setEncodings = mock.Mock()
    cli.requested_jpeg_quality = jpeg_quality
    cli.vncConnectionMade()
    return cli.setEncodings.call_args.args[0]


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
    for level in range(len(client.JPEG_QUALITY_ENCODINGS)):
        name = f"TestJpegQualityLevel_{level}"
        case = type(name, (JpegQualityLevel, TestCase), {"level": level})
        suite.addTest(case("test_offers_the_pseudo_encoding_that_carries_it"))
    return suite
