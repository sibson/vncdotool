import socket
import unittest
from unittest import mock, skipUnless

from vncdotool import command


class TestBuildCommandList(unittest.TestCase):

    def setUp(self) -> None:
        super().setUp()
        self.factory = mock.Mock()
        self.client = command.VNCDoCLIClient
        self.deferred = self.factory.deferred

    def assertCalled(self, fn, *args) -> None:
        self.deferred.addCallback.assert_called_with(fn, *args)

    def call_build_commands_list(self, commands, **kwargs) -> None:
        command.build_command_list(self.factory, commands.split(), **kwargs)

    def test_alphanum_key(self) -> None:
        self.call_build_commands_list('key a')
        self.assertCalled(self.client.keyPress, 'a')

    def test_control_key(self) -> None:
        self.call_build_commands_list('key ctrl-c')
        self.assertCalled(self.client.keyPress, 'ctrl-c')

    def test_keyup(self) -> None:
        self.call_build_commands_list('keyup a')
        self.assertCalled(self.client.keyUp, 'a')

    def test_keydown(self) -> None:
        self.call_build_commands_list('keydown a')
        self.assertCalled(self.client.keyDown, 'a')

    def test_key_missing(self) -> None:
        pass

    def test_move(self) -> None:
        self.call_build_commands_list('move 100 200')
        self.assertCalled(self.client.mouseMove, 100, 200)

    def test_mousemove(self) -> None:
        self.call_build_commands_list('mousemove 100 200')
        self.assertCalled(self.client.mouseMove, 100, 200)

    def test_move_missing(self) -> None:
        pass

    def test_click(self) -> None:
        self.call_build_commands_list('click 1')
        self.assertCalled(self.client.mousePress, 1)

    def test_click_missing(self) -> None:
        pass

    def test_type(self) -> None:
        self.call_build_commands_list('type foobar')
        call = self.factory.deferred.addCallback
        for key in 'foobar':
            call.assert_any_call(self.client.keyPress, key)

    def test_type_missing(self) -> None:
        pass

    def test_capture(self):
        command.SUPPORTED_FORMATS = ('png',)
        command.os.path.splitext.return_value = 'capture', '.png'
        self.call_build_commands_list('capture foo.png')
        self.assertCalled(self.client.captureScreen, 'foo.png', 0)

    def test_capture_not_supported(self):
        command.SUPPORTED_FORMATS = ('png',)
        command.os.path.splitext.return_value = 'capture', '.mpeg'
        with self.assertRaises(command.CommandParseError):
            self.call_build_commands_list('capture foo.mpeg')
        self.assertFalse(self.deferred.addCallback.called)

    def test_capture_missing_filename(self) -> None:
        pass

    def test_expect(self) -> None:
        self.call_build_commands_list('expect foo.png 10')
        self.assertCalled(self.client.expectScreen, 'foo.png', 10)

    def test_expect_not_png(self) -> None:
        pass

    def test_expect_missing(self) -> None:
        pass

    def test_chain_key_commands(self) -> None:
        self.call_build_commands_list('type foobar key enter')
        call = self.factory.deferred.addCallback
        for key in 'foobar':
            call.assert_any_call(self.client.keyPress, key)
        call.assert_any_call(self.client.keyPress, 'enter')

    def test_chain_type_expect(self) -> None:
        self.call_build_commands_list('type username expect password.png 0')
        call = self.factory.deferred.addCallback
        for key in 'username':
            call.assert_any_call(self.client.keyPress, key)

        call.assert_any_call(self.client.expectScreen, 'password.png', 0)

    def test_pause(self) -> None:
        self.call_build_commands_list('pause 0.3')
        self.assertCalled(self.client.pause, 0.3)

    def test_sleep(self) -> None:
        self.call_build_commands_list('sleep 1')
        self.assertCalled(self.client.pause, 1)

    def test_pause_warp(self) -> None:
        self.call_build_commands_list('pause 10', warp=5)
        self.assertCalled(self.client.pause, 2.0)

    def test_mousedown(self) -> None:
        self.call_build_commands_list('mousedown 1')
        self.assertCalled(self.client.mouseDown, 1)

        self.call_build_commands_list('mdown 2')
        self.assertCalled(self.client.mouseDown, 2)

    def test_mouseup(self) -> None:
        self.call_build_commands_list('mouseup 1')
        self.assertCalled(self.client.mouseUp, 1)

        self.call_build_commands_list('mup 2')
        self.assertCalled(self.client.mouseUp, 2)

    def test_drag(self) -> None:
        self.call_build_commands_list('drag 100 200')
        self.assertCalled(self.client.mouseDrag, 100, 200)

    def test_insert_delay(self) -> None:
        self.call_build_commands_list('click 1 key a', delay=100)
        expected = [
            mock.call(self.client.mousePress, 1),
            mock.call(self.client.pause, 0.1),
            mock.call(self.client.keyPress, 'a'),
        ]

        self.assertEqual(self.deferred.addCallback.call_args_list, expected)


class TestParseServer(unittest.TestCase):

    def test_default(self) -> None:
        family, host, port = command.parse_server('')
        assert family == socket.AF_INET
        assert host == '127.0.0.1'
        assert port == 5900

    def test_host_display(self) -> None:
        family, host, port = command.parse_server('10.11.12.13:10')
        assert family == socket.AF_INET
        assert host == '10.11.12.13'
        assert port == 5910

    def test_host_port(self) -> None:
        family, host, port = command.parse_server('10.11.12.13::4444')
        assert family == socket.AF_INET
        assert host == '10.11.12.13'
        assert port == 4444

    def test_just_host(self) -> None:
        family, host, port = command.parse_server('10.11.12.13')
        assert family == socket.AF_INET
        assert host == '10.11.12.13'
        assert port == 5900

    def test_just_display(self) -> None:
        family, host, port = command.parse_server(':10')
        assert family == socket.AF_INET
        assert host == '127.0.0.1'
        assert port == 5910

    def test_missing_display(self) -> None:
        with self.assertRaises(ValueError):
            command.parse_server(":")

    def test_missing_port(self) -> None:
        with self.assertRaises(ValueError):
            command.parse_server("::")

    def test_invalid(self) -> None:
        with self.assertRaises(ValueError):
            command.parse_server(":::")

    def test_just_port(self) -> None:
        family, host, port = command.parse_server('::1111')
        assert family == socket.AF_INET
        assert host == '127.0.0.1'
        assert port == 1111

    def test_ipv6_host_display(self) -> None:
        family, host, port = command.parse_server('[::1]:10')
        assert family == socket.AF_INET6
        assert host == '::1'
        assert port == 5910

    def test_ipv6_host_port(self) -> None:
        family, host, port = command.parse_server('[::1]::4444')
        assert family == socket.AF_INET6
        assert host == '::1'
        assert port == 4444

    def test_ipv6_just_host(self) -> None:
        family, host, port = command.parse_server('[::1]')
        assert family == socket.AF_INET6
        assert host == '::1'
        assert port == 5900

    def test_ipv6_broken(self) -> None:
        with self.assertRaises(ValueError):
            command.parse_server("[::1")

    @skipUnless(hasattr(socket, "AF_UNIX"), reason="AF_UNIX not supported by old Windows")
    @mock.patch("os.path.exists")
    def test_unix_socket(self, exists) -> None:
        exists.return_value = True
        family, host, port = command.parse_server('/some/path/unix.skt')
        assert family == socket.AF_UNIX
        assert host == '/some/path/unix.skt'
        assert port == 5900

    def test_dns_name(self) -> None:
        family, host, port = command.parse_server('localhost')
        assert family == socket.AF_UNSPEC
        assert host == 'localhost'
        assert port == 5900


class TestVNCDoCLIClient(unittest.TestCase):

    def setUp(self) -> None:
        self.client = command.VNCDoCLIClient()
        self.client.factory = mock.Mock()

    @mock.patch('getpass.getpass')
    def test_vncRequestPassword_prompt(self, getpass):
        cli = self.client
        cli.factory.password = None
        cli.sendPassword = mock.Mock()
        cli.vncRequestPassword()

        password = command.getpass.getpass.return_value
        assert command.getpass.getpass.called
        assert cli.factory.password == password
        cli.sendPassword.assert_called_once_with(password)
