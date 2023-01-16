from unittest import TestCase, mock

from vncdotool import client, rfb


class TestVNCDoToolClient(TestCase):

    def setUp(self):
        self.client = client.VNCDoToolClient()
        self.client.transport = mock.Mock()
        self.client.factory = mock.Mock()

        # mock out a bunch of base class functions
        self.client.framebufferUpdateRequest = mock.Mock()
        self.client.pointerEvent = mock.Mock()
        self.client.keyEvent = mock.Mock()
        self.client.setEncodings = mock.Mock()

    def test_vncConnectionMade(self):
        cli = self.client
        cli._packet = bytearray(b"RFB 003.003\n")
        cli._handleInitial()
        cli._handleServerInit(b" " * 24)
        cli.vncConnectionMade()
        factory = cli.factory
        factory.clientConnectionMade.assert_called_once_with(cli)
        self.client.setEncodings.assert_called_once_with([
            client.rfb.RAW_ENCODING,
            client.rfb.PSEUDO_CURSOR_ENCODING,
            client.rfb.PSEUDO_DESKTOP_SIZE_ENCODING])

    def test_keyPress_single_alpha(self):
        cli = self.client
        cli.keyPress('a')
        cli.keyEvent.assert_any_call(ord('a'), down=1)
        cli.keyEvent.assert_any_call(ord('a'), down=0)

    def test_keyPress_multiple(self):
        cli = self.client
        cli.keyPress('ctrl-alt-del')

        # XXX doesn't ensure correct order
        cli.keyEvent.assert_any_call(rfb.KEY_ControlLeft, down=1)
        cli.keyEvent.assert_any_call(rfb.KEY_AltLeft, down=1)
        cli.keyEvent.assert_any_call(rfb.KEY_Delete, down=1)
        cli.keyEvent.assert_any_call(rfb.KEY_ControlLeft, down=0)
        cli.keyEvent.assert_any_call(rfb.KEY_AltLeft, down=0)
        cli.keyEvent.assert_any_call(rfb.KEY_Delete, down=0)

    @mock.patch('vncdotool.client.Deferred')
    def test_captureScreen(self, Deferred):
        cli = self.client
        cli._packet = bytearray(b"RFB 003.003\n")
        cli._handleInitial()
        cli._handleServerInit(b" " * 24)
        cli.vncConnectionMade()
        fname = 'foo.png'

        d = cli.captureScreen(fname)
        d.addCallback.assert_called_once_with(cli._captureSave, fname)
        assert cli.framebufferUpdateRequest.called

    def test_captureSave(self):
        cli = self.client
        cli.screen = mock.Mock()
        fname = 'foo.png'
        r = cli._captureSave(cli.screen, fname)
        cli.screen.save.assert_called_once_with(fname)
        assert r == cli

    @mock.patch('PIL.Image.open')
    @mock.patch('vncdotool.client.Deferred')
    def test_expectScreen(self, Deferred, image_open):
        cli = self.client
        cli._packet = bytearray(b"RFB 003.003\n")
        cli._handleInitial()
        cli._handleServerInit(b" " * 24)
        cli.vncConnectionMade()
        fname = 'something.png'

        region = (0 ,0, 11, 22)
        client.Image.open.return_value.size = region[2:]

        d = cli.expectScreen(fname, 5)
        assert cli.framebufferUpdateRequest.called

        image_open.assert_called_once_with(fname)

        assert cli.expected == client.Image.open.return_value.histogram.return_value
        Deferred.return_value.addCallback.assert_called_once_with(cli._expectCompare, region, 5)

    def test_expectCompareSuccess(self):
        cli = self.client
        d = cli.deferred = mock.Mock()
        cli.expected = [2, 2, 2]
        cli.screen = mock.Mock()
        cli.screen.histogram.return_value = [1, 2, 3]
        cli.screen.crop.return_value = cli.screen
        result = cli._expectCompare(cli, None, 5)
        assert result == cli

    def test_expectCompareExactSuccess(self):
        cli = self.client
        d = cli.deferred = mock.Mock()
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
        data = mock.Mock()

        cli.updateRectangle(0, 0, 100, 200, data)

        client.Image.frombytes.assert_called_once_with('RGB', (100, 200), data, 'raw', 'RGBX')

        assert cli.screen == client.Image.frombytes.return_value

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

    def test_commitUpdate(self):
        rects = mock.Mock()
        self.deferred = mock.Mock()
        self.client.deferred = self.deferred
        self.client.commitUpdate(rects)

        self.deferred.callback.assert_called_once_with(self.client)

    def test_vncRequestPassword_attribute(self):
        cli = self.client
        cli.sendPassword = mock.Mock()
        cli.factory.password = 'mushroommushroom'
        cli.vncRequestPassword()
        cli.sendPassword.assert_called_once_with(cli.factory.password)


class TestVNCDoToolFactory(TestCase):

    def setUp(self):
        self.factory = client.VNCDoToolFactory()

    def test_init(self):
        assert self.factory.deferred

    def test_clientConnectionMade(self):
        deferred = mock.Mock()
        protocol = mock.Mock()
        self.factory.deferred = deferred

        self.factory.clientConnectionMade(protocol)

        deferred.callback.assert_called_once_with(protocol)

    def test_clientConnectionFailed(self):
        deferred = mock.Mock()
        self.factory.deferred = deferred
        reason = mock.Mock()
        connector = mock.Mock()

        self.factory.clientConnectionFailed(connector, reason)

        deferred.errback.assert_called_once_with(reason)
