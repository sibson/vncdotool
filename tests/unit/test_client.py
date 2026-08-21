from unittest import TestCase, mock
import io
import struct
import warnings

from vncdotool import client, pixelformat, rfb
from vncdotool.keys import Key

COLOUR_MAPPED = rfb.PixelFormat(8, 8, False, False, 0, 0, 0, 0, 0, 0)


class TestVNCDoToolClient(TestCase):

    MSG_HANDSHAKE = b"RFB 003.003\n"
    MSG_INIT = (
        b"\x00\x00"  # width
        b"\x00\x00"  # height
        b"\x20\x18\x00\x01\x00\xff\x00\xff\x00\xff\x00\x08\x10\x00\x00\x00"  # pixel-format
        b"\x00\x00\x00\x00"  # server-name-len
    )

    def setUp(self) -> None:
        self.client = client.VNCDoToolClient()
        self.client.transport = mock.Mock()
        self.client.factory = mock.Mock()

        # mock out a bunch of base class functions
        self.client.framebufferUpdateRequest = mock.Mock()  # type: ignore[assignment]
        self.client.pointerEvent = mock.Mock()  # type: ignore[assignment]
        self.client.keyEvent = mock.Mock()  # type: ignore[assignment]
        self.client.setEncodings = mock.Mock()  # type: ignore[assignment]

    def test_vncConnectionMade(self):
        cli = self.client
        cli._packet = bytearray(self.MSG_HANDSHAKE)
        cli._handleInitial()
        cli._handleServerInit(self.MSG_INIT)
        factory = cli.factory
        factory.clientConnectionMade.assert_called_once_with(cli)
        self.client.setEncodings.assert_called_once_with([
            client.rfb.Encoding.RAW,
            client.rfb.Encoding.PSEUDO_CURSOR,
            client.rfb.Encoding.PSEUDO_DESKTOP_SIZE,
            client.rfb.Encoding.PSEUDO_LAST_RECT,
            client.rfb.Encoding.PSEUDO_QEMU_EXTENDED_KEY_EVENT,
        ])

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

        assert cli.expected == client.Image.open.return_value.histogram.return_value
        Deferred.return_value.addCallback.assert_called_once_with(cli._expectCompare, region, 5)

    def test_expectCompareSuccess(self) -> None:
        cli = self.client
        cli.deferred = mock.Mock()
        cli.expected = [2, 2, 2]
        cli.screen = mock.Mock()
        cli.screen.histogram.return_value = [1, 2, 3]
        cli.screen.crop.return_value = cli.screen
        result = cli._expectCompare(cli, None, 5)
        assert result == cli

    def test_expectCompareExactSuccess(self) -> None:
        cli = self.client
        cli.deferred = mock.Mock()
        cli.expected = [2, 2, 2]
        cli.screen = mock.Mock()
        cli.screen.histogram.return_value = [2, 2, 2]
        cli.screen.crop.return_value = cli.screen
        result = cli._expectCompare(cli, None, 0)
        assert result == cli

    @mock.patch('vncdotool.client.Deferred')
    def test_expectCompareFails(self, Deferred):
        cli = self.client
        cli.deferred = mock.Mock()
        cli.expected = [2, 2, 2]
        cli.framebufferUpdateRequest = mock.Mock()
        cli.screen = mock.Mock()
        cli.screen.histogram.return_value = [1, 1, 1]
        cli.screen.crop.return_value = cli.screen

        result = cli._expectCompare(cli, None, 0)

        assert result != cli
        assert result == cli.deferred
        assert not cli.deferred.callback.called

        cli.framebufferUpdateRequest.assert_called_once_with(incremental=1)
        cli.deferred.addCallback.assert_called_once_with(cli._expectCompare, None, 0)

    @mock.patch('vncdotool.client.Deferred')
    def test_expectCompareMismatch(self, Deferred):
        cli = self.client
        cli.deferred = mock.Mock()
        cli.expected = [2, 2]
        cli.framebufferUpdateRequest = mock.Mock()
        cli.screen = mock.Mock()
        cli.screen.histogram.return_value = [1, 1, 1]
        cli.screen.crop.return_value = cli.screen

        result = cli._expectCompare(cli, None, 0)

        assert result != cli
        assert result == cli.deferred
        assert not cli.deferred.callback.called

        cli.framebufferUpdateRequest.assert_called_once_with(incremental=1)
        cli.deferred.addCallback.assert_called_once_with(cli._expectCompare, None, 0)

    @mock.patch('PIL.Image.frombytes')
    def test_updateRectangeFullScreen(self, frombytes):
        cli = self.client
        cli.image = mock.Mock()
        cli.width, cli.height = 100, 200
        data = mock.Mock()
        frombytes.return_value = client.Image.new("RGB", (100, 200), (10, 20, 30))

        cli.updateRectangle(0, 0, 100, 200, data)

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
        cli.updateRectangle(50, 30, 10, 10, data)

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

        cli.updateRectangle(20, 10, 50, 40, data)

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
        cli.framebufferUpdateRequest.assert_called_once_with()

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

    def test_image_mode_warns_on_access(self):
        with self.assertWarns(FutureWarning):
            self.client.image_mode

    def test_image_mode_returns_negotiated_mode(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            assert self.client.image_mode == "RGBX"

    def test_setImageMode_does_not_warn(self):
        self.client._version_server = (3, 8)
        self.client.pixel_format = client.RGB24
        self.client.setPixelFormat = mock.Mock()  # type: ignore[assignment]

        with warnings.catch_warnings():
            warnings.simplefilter("error", FutureWarning)
            self.client.setImageMode()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            assert self.client.image_mode == "RGB"

    def test_setImageMode_falls_back_for_apple_remote_desktop(self):
        self.client._version_server = (3, 889)
        self.client.pixel_format = COLOUR_MAPPED
        self.client.setPixelFormat = mock.Mock()  # type: ignore[assignment]

        self.client.setImageMode()

        self.client.setPixelFormat.assert_called_once_with(client.BGR16)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            assert self.client.image_mode == "BGR;16"

    def test_setImageMode_falls_back_when_the_server_format_cannot_be_unpacked(self):
        self.client._version_server = (3, 8)
        self.client.pixel_format = COLOUR_MAPPED
        self.client.setPixelFormat = mock.Mock()  # type: ignore[assignment]

        self.client.setImageMode()

        self.client.setPixelFormat.assert_called_once_with(client.RGB32)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            assert self.client.image_mode == "RGBX"

    def test_setImageMode_keeps_a_server_format_pillow_can_unpack(self):
        self.client._version_server = (3, 8)
        self.client.pixel_format = rfb.PixelFormat(32, 24, False, True, 255, 255, 255, 24, 16, 8)
        self.client.setPixelFormat = mock.Mock()  # type: ignore[assignment]

        self.client.setImageMode()

        self.client.setPixelFormat.assert_not_called()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            assert self.client.image_mode == "XBGR"

    def test_setImageMode_asks_for_the_format_the_caller_requested(self):
        self.client._version_server = (3, 8)
        self.client.pixel_format = client.RGB32
        self.client.requested_pixel_format = client.BGR16
        self.client.setPixelFormat = mock.Mock()  # type: ignore[assignment]

        self.client.setImageMode()

        self.client.setPixelFormat.assert_called_once_with(client.BGR16)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            assert self.client.image_mode == "BGR;16"

    def test_setImageMode_keeps_bypp_in_step_with_the_negotiated_format(self):
        # setPixelFormat is real here, not mocked like the tests above: bypp
        # is a read-through of the pixel_format it assigns, so a mock hides
        # any drift between it and the raw mode _image_mode negotiates.
        self.client._version_server = (3, 8)
        self.client.pixel_format = client.RGB32
        self.client.requested_pixel_format = client.BGR16

        self.client.setImageMode()

        assert self.client.bypp == client.BGR16.bypp
        assert self.client._image_mode == pixelformat.raw_mode(client.BGR16)

    @mock.patch('PIL.Image.frombytes')
    def test_updateRectangle_does_not_warn(self, frombytes):
        cli = self.client
        cli.image = mock.Mock()
        cli.width, cli.height = 100, 200
        frombytes.return_value = client.Image.new("RGB", (100, 200))

        with warnings.catch_warnings():
            warnings.simplefilter("error", FutureWarning)
            cli.updateRectangle(0, 0, 100, 200, mock.Mock())

    def test_updateCursor_does_not_warn(self):
        cli = self.client
        cli.factory.nocursor = False

        with warnings.catch_warnings():
            warnings.simplefilter("error", FutureWarning)
            cli.updateCursor(0, 0, 4, 4, b"\x00" * (4 * 4 * 4), b"\x00" * 4)


class TestVMWareClient(TestCase):

    def setUp(self) -> None:
        self.client = client.VMWareClient()
        self.client.transport = mock.Mock()
        self.client.factory = mock.Mock()
        self.client.framebufferUpdateRequest = mock.Mock()  # type: ignore[assignment]
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
        factory.pixel_format = client.BGR16

        assert factory.buildProtocol(None).requested_pixel_format == client.BGR16

    def test_clients_ask_for_nothing_by_default(self):
        assert client.VNCDoToolFactory().buildProtocol(None).requested_pixel_format is None
