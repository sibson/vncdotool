import contextlib
import io
import logging
import os
import socket
import tempfile
import unittest
from unittest import mock, skipUnless

from twisted.internet.error import ConnectionDone, ConnectionRefusedError, DNSLookupError
from twisted.python.failure import Failure

from vncdotool import command, pixelformat
from vncdotool.client import AuthenticationError, ProtocolError, RegionError
from vncdotool.loggingproxy import VNCLoggingServerProxy
from vncdotool.replay import Capture


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

    def test_expect_without_a_fuzz(self) -> None:
        self.call_build_commands_list('expect foo.png')
        self.assertCalled(self.client.expectScreen, 'foo.png', None)

    def test_expect_without_a_fuzz_before_another_command(self) -> None:
        self.call_build_commands_list('expect foo.png key enter')
        call = self.factory.deferred.addCallback
        call.assert_any_call(self.client.expectScreen, 'foo.png', None)
        call.assert_any_call(self.client.keyPress, 'enter')

    def test_rexpect(self) -> None:
        self.call_build_commands_list('rexpect foo.png 10 20 30')
        self.assertCalled(self.client.expectRegion, 'foo.png', 10, 20, 30)

    def test_rexpect_without_a_fuzz(self) -> None:
        self.call_build_commands_list('rexpect foo.png 10 20')
        self.assertCalled(self.client.expectRegion, 'foo.png', 10, 20, None)

    def test_expect_rejects_a_fractional_fuzz(self) -> None:
        with self.assertRaises(command.CommandParseError):
            self.call_build_commands_list('expect foo.png 0.5')

    def test_expect_rejects_a_fuzz_off_the_scale(self) -> None:
        for fuzz in ('-1', '256'):
            with self.subTest(fuzz=fuzz):
                with self.assertRaises(command.CommandParseError):
                    self.call_build_commands_list(f'expect foo.png {fuzz}')

    def test_stable(self) -> None:
        self.call_build_commands_list('stable 1.5 10')
        self.assertCalled(self.client.stableScreen, 1.5, 10)

    def test_stable_without_a_fuzz(self) -> None:
        self.call_build_commands_list('stable 1.5')
        self.assertCalled(self.client.stableScreen, 1.5, None)

    def test_stable_without_a_fuzz_before_another_command(self) -> None:
        self.call_build_commands_list('stable 1.5 key enter')
        call = self.factory.deferred.addCallback
        call.assert_any_call(self.client.stableScreen, 1.5, None)
        call.assert_any_call(self.client.keyPress, 'enter')

    def test_rstable(self) -> None:
        self.call_build_commands_list('rstable 1.5 100 200 400 250 10')
        self.assertCalled(self.client.stableRegion, 1.5, 100, 200, 400, 250, 10)

    def test_rstable_without_a_fuzz(self) -> None:
        self.call_build_commands_list('rstable 1.5 100 200 400 250')
        self.assertCalled(self.client.stableRegion, 1.5, 100, 200, 400, 250, None)

    def test_stable_rejects_a_fuzz_off_the_scale(self) -> None:
        with self.assertRaises(command.CommandParseError):
            self.call_build_commands_list('stable 1.5 256')

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

    def test_drag_rejects_a_prefix_of_itself(self) -> None:
        with self.assertRaises(command.CommandParseError):
            self.call_build_commands_list('dra 100 200')

    def test_drag_rejects_an_infix_of_itself(self) -> None:
        with self.assertRaises(command.CommandParseError):
            self.call_build_commands_list('ra 100 200')

    def test_insert_delay(self) -> None:
        self.call_build_commands_list('click 1 key a', delay=100)
        expected = [
            mock.call(self.client.mousePress, 1),
            mock.call(self.client.pause, 0.1),
            mock.call(self.client.keyPress, 'a'),
        ]

        self.assertEqual(self.deferred.addCallback.call_args_list, expected)


class TestSessionVdoRoundTrip(unittest.TestCase):
    """A session.vdo recorded by VNCLoggingServerProxy.handle_keyEvent must
    parse back cleanly through build_command_list's shlex(posix=True) file
    reader, including keysyms with no KEYMAP name (', ", #, backslash)."""

    def record_keys(self, chars: str) -> str:
        sp = VNCLoggingServerProxy()
        sp.last_event = 0.0
        recorded: list[str] = []
        sp.recorder = recorded.append
        for ch in chars:
            sp.handle_keyEvent(ord(ch), True)
            sp.handle_keyEvent(ord(ch), False)
        return "".join(recorded)

    def build_from_script(self, script_text: str) -> mock.Mock:
        factory = mock.Mock()
        with tempfile.NamedTemporaryFile("w", suffix=".vdo", delete=False) as fh:
            fh.write(script_text)
            path = fh.name
        self.addCleanup(os.unlink, path)
        command.build_command_list(factory, [path])
        return factory

    def test_quote_and_hash_round_trip(self) -> None:
        factory = self.build_from_script(self.record_keys("'#"))

        call = factory.deferred.addCallback
        client = command.VNCDoCLIClient
        call.assert_any_call(client.keyDown, "'")
        call.assert_any_call(client.keyUp, "'")
        call.assert_any_call(client.keyDown, "#")
        call.assert_any_call(client.keyUp, "#")


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


class TestExitStatus(unittest.TestCase):

    def test_documented_values(self) -> None:
        # these are a published interface, see docs/usage.rst
        assert dict(command.ExitStatus.__members__.items()) == {
            'SUCCESS': 0,
            'ERROR': 1,
            'USAGE': 2,
            'AUTHENTICATION_FAILED': 3,
            'CONNECTION_FAILED': 10,
            'CONNECTION_LOST': 11,
            'PROTOCOL_ERROR': 20,
            'COMMAND_FAILED': 30,
            'TIMEOUT': 40,
        }


class FakeReactor:
    """Records the exit status instead of stopping the real reactor.

    A bare Mock would report an auto-created attribute for exit_status, which
    the factory reads as an outcome having already been decided.
    """

    def __init__(self) -> None:
        self.exit_status = None

    def callLater(self, delay, fn, *args, **kwargs) -> None:
        pass

    def stop(self) -> None:
        pass


@mock.patch('vncdotool.command.reactor', new_callable=FakeReactor)
class TestVNCDoCLIFactory(unittest.TestCase):

    def setUp(self) -> None:
        self.factory = command.VNCDoCLIFactory()
        self.stderr = io.StringIO()
        patcher = mock.patch('sys.stderr', self.stderr)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_auth_failure(self, reactor) -> None:
        self.factory.clientConnectionFailed(
            None, Failure(AuthenticationError('Authentication failure'))
        )

        assert reactor.exit_status == command.ExitStatus.AUTHENTICATION_FAILED

    def test_protocol_error(self, reactor) -> None:
        self.factory.clientConnectionFailed(
            None, Failure(ProtocolError('unknown encoding received'))
        )

        assert reactor.exit_status == command.ExitStatus.PROTOCOL_ERROR

    def test_connection_refused(self, reactor) -> None:
        self.factory.clientConnectionFailed(None, Failure(ConnectionRefusedError()))

        assert reactor.exit_status == command.ExitStatus.CONNECTION_FAILED

    def test_dns_lookup_failure(self, reactor) -> None:
        self.factory.clientConnectionFailed(None, Failure(DNSLookupError()))

        assert reactor.exit_status == command.ExitStatus.CONNECTION_FAILED

    def test_clean_close_before_commands_run(self, reactor) -> None:
        # the server hanging up cleanly is not evidence the commands ran
        self.factory.clientConnectionLost(None, Failure(ConnectionDone()))

        assert reactor.exit_status == command.ExitStatus.CONNECTION_LOST

    def test_command_failure(self, reactor) -> None:
        self.factory.error(Failure(IOError('cannot write capture')))

        assert reactor.exit_status == command.ExitStatus.COMMAND_FAILED

    def test_region_off_the_screen(self, reactor) -> None:
        self.factory.error(Failure(RegionError('region (0, 0, 1, 1) is not inside the 0x0 screen')))

        assert reactor.exit_status == command.ExitStatus.COMMAND_FAILED

    def test_timeout(self, reactor) -> None:
        self.factory.error(Failure(command.TimeoutError('TIMEOUT Exceeded (5s)')))

        assert reactor.exit_status == command.ExitStatus.TIMEOUT

    def test_clean_close_after_commands_run_keeps_success(self, reactor) -> None:
        self.factory.done(command.ExitStatus.SUCCESS)
        self.factory.clientConnectionLost(None, Failure(ConnectionDone()))

        assert reactor.exit_status == command.ExitStatus.SUCCESS

    def test_failure_is_reported_as_a_cli_error(self, reactor) -> None:
        self.factory.clientConnectionFailed(None, Failure(ConnectionRefusedError()))

        self.assertEqual(self.stderr.getvalue().strip(), str(ConnectionRefusedError()))

    def test_failure_traceback_is_a_verbose_diagnostic(self, reactor) -> None:
        with self.assertLogs(command.log, logging.DEBUG) as logged:
            self.factory.error(Failure(IOError('cannot write capture')))

        self.assertIn('Traceback', '\n'.join(logged.output))
        self.assertEqual([r.levelno for r in logged.records], [logging.DEBUG])

    def test_first_outcome_wins(self, reactor) -> None:
        self.factory.error(Failure(AuthenticationError('denied')))
        self.factory.done(command.ExitStatus.SUCCESS)

        assert reactor.exit_status == command.ExitStatus.AUTHENTICATION_FAILED


@mock.patch('vncdotool.command.factory_connect')
@mock.patch('vncdotool.command.reactor', new_callable=FakeReactor)
class TestBuildTool(unittest.TestCase):

    def setUp(self) -> None:
        self.options = mock.Mock(
            verbose=False,
            delay=None,
            warp=1.0,
            incremental_refreshes=0,
            host='127.0.0.1',
            port=5900,
            address_family=socket.AF_INET,
        )

    def test_undecided_exit_status_starts_none(self, reactor, connect) -> None:
        reactor.exit_status = 'left over from an earlier run'

        command.build_tool(self.options, [])

        assert reactor.exit_status is None

    def test_completed_commands_close_connection_and_exit_zero(
        self, reactor, connect
    ) -> None:
        factory = command.build_tool(self.options, [])
        client = mock.Mock()

        factory.deferred.callback(client)

        client.transport.loseConnection.assert_called_once_with()
        assert reactor.exit_status == command.ExitStatus.SUCCESS

    def test_failed_command_exits_command_failed(self, reactor, connect) -> None:
        factory = command.build_tool(self.options, [])

        factory.deferred.errback(Failure(IOError('cannot write capture')))

        assert reactor.exit_status == command.ExitStatus.COMMAND_FAILED

    def test_unparsable_command_exits_usage(self, reactor, connect) -> None:
        with self.assertRaises(SystemExit) as raised:
            command.build_tool(self.options, ['nosuchcommand'])

        assert raised.exception.code == command.ExitStatus.USAGE


@mock.patch('vncdotool.command.factory_connect')
@mock.patch('vncdotool.command.reactor', new_callable=FakeReactor)
class TestVncdoArgvParameter(unittest.TestCase):
    """vncdo(argv) must feed the parser instead of mutating sys.argv, so a
    caller like _replay_client can build a synthetic invocation directly."""

    def test_argv_parameter_is_what_gets_parsed(self, reactor, connect) -> None:
        with self.assertRaises(SystemExit) as raised:
            command.vncdo(['nosuchcommand'])

        assert raised.exception.code == command.ExitStatus.USAGE

    def test_a_leading_option_looking_number_is_a_usage_error(self, reactor, connect) -> None:
        with self.assertRaises(SystemExit) as raised:
            command.vncdo(['-10', '20'])

        assert raised.exception.code == command.ExitStatus.USAGE

    def test_no_argv_reports_missing_command(self, reactor, connect) -> None:
        with self.assertRaises(SystemExit) as raised:
            command.vncdo([])

        assert raised.exception.code == command.ExitStatus.USAGE


@mock.patch('vncdotool.command.factory_connect')
@mock.patch('vncdotool.command.reactor', new_callable=mock.MagicMock)
class TestVncdoPixelFormatOption(unittest.TestCase):

    def test_pixel_format_option_sets_factory_pixel_format(self, reactor, connect) -> None:
        with self.assertRaises(SystemExit):
            command.vncdo(['-s', '127.0.0.1::5900', '--pixel-format', 'rgb565', 'key', 'a'])

        factory = connect.call_args.args[0]
        assert factory.pixel_format == pixelformat.PIXEL_FORMATS['rgb565']


@mock.patch('vncdotool.command.factory_connect')
@mock.patch('vncdotool.command.reactor', new_callable=mock.MagicMock)
class TestVncdoJpegQualityOption(unittest.TestCase):

    def test_a_level_reaches_the_factory(self, reactor, connect) -> None:
        with self.assertRaises(SystemExit):
            command.vncdo(['-s', '127.0.0.1::5900', '--encodings', 'tight',
                           '--jpeg-quality', '9', 'key', 'a'])

        assert connect.call_args.args[0].jpeg_quality == 9

    def test_a_level_without_tight_is_a_usage_error(self, reactor, connect) -> None:
        with self.assertRaises(SystemExit) as raised:
            command.vncdo(['-s', '127.0.0.1::5900', '--encodings', 'zrle',
                           '--jpeg-quality', '9', 'key', 'a'])

        assert raised.exception.code == command.ExitStatus.USAGE

    def test_a_level_needs_no_encodings_flag(self, reactor, connect) -> None:
        """Tight is on the default list, so --jpeg-quality alone applies."""
        with self.assertRaises(SystemExit):
            command.vncdo(['-s', '127.0.0.1::5900', '--jpeg-quality', '9', 'key', 'a'])

        assert connect.call_args.args[0].jpeg_quality == 9

    def test_without_the_flag_no_level_is_offered(self, reactor, connect) -> None:
        with self.assertRaises(SystemExit):
            command.vncdo(['-s', '127.0.0.1::5900', 'key', 'a'])

        assert connect.call_args.args[0].jpeg_quality is None

    def test_a_level_outside_the_ten_is_a_usage_error(self, reactor, connect) -> None:
        for level in ('-1', '10'):
            with self.subTest(level=level):
                with self.assertRaises(SystemExit) as raised:
                    command.vncdo(['-s', '127.0.0.1::5900', '--jpeg-quality', level, 'key', 'a'])

                assert raised.exception.code == command.ExitStatus.USAGE


@mock.patch('vncdotool.command.factory_connect')
@mock.patch('vncdotool.command.reactor', new_callable=mock.MagicMock)
class TestVncdoExpectOptions(unittest.TestCase):

    def test_both_reach_the_factory(self, reactor, connect) -> None:
        with self.assertRaises(SystemExit):
            command.vncdo(['-s', '127.0.0.1::5900', '--fuzz', '64',
                           '--blur', '2', 'key', 'a'])

        factory = connect.call_args.args[0]
        assert factory.fuzz == 64
        assert factory.blur == 2

    def test_without_the_flags_the_format_decides(self, reactor, connect) -> None:
        with self.assertRaises(SystemExit):
            command.vncdo(['-s', '127.0.0.1::5900', 'key', 'a'])

        factory = connect.call_args.args[0]
        assert factory.fuzz is None
        assert factory.blur == 0

    def test_a_jpeg_quality_blurs_without_being_asked(self, reactor, connect) -> None:
        with self.assertRaises(SystemExit):
            command.vncdo(['-s', '127.0.0.1::5900', '--encodings', 'tight',
                           '--jpeg-quality', '5', 'key', 'a'])

        assert connect.call_args.args[0].blur == command.LOSSY_BLUR

    def test_an_explicit_blur_beats_the_jpeg_default(self, reactor, connect) -> None:
        with self.assertRaises(SystemExit):
            command.vncdo(['-s', '127.0.0.1::5900', '--encodings', 'tight',
                           '--jpeg-quality', '5', '--blur', '0', 'key', 'a'])

        assert connect.call_args.args[0].blur == 0

    def test_a_fuzz_off_the_scale_is_a_usage_error(self, reactor, connect) -> None:
        for fuzz in ('-1', '256'):
            with self.subTest(fuzz=fuzz):
                with self.assertRaises(SystemExit) as raised:
                    command.vncdo(['-s', '127.0.0.1::5900', '--fuzz', fuzz, 'key', 'a'])

                assert raised.exception.code == command.ExitStatus.USAGE

    def test_a_negative_blur_is_a_usage_error(self, reactor, connect) -> None:
        with self.assertRaises(SystemExit) as raised:
            command.vncdo(['-s', '127.0.0.1::5900', '--blur', '-1', 'key', 'a'])

        assert raised.exception.code == command.ExitStatus.USAGE


class TestReplayClient(unittest.TestCase):
    """_replay_client turns a loaded Capture into a `vncdo` invocation."""

    def setUp(self) -> None:
        self.op = mock.Mock()
        self.options = mock.Mock(connect='127.0.0.1::5999', password=None)

    def make_capture(self, session_vdo: bytes = b'', auth_preserved: bool = False) -> Capture:
        meta = {'auth': 'preserved'} if auth_preserved else None
        return Capture(s2c=b'', session_vdo=session_vdo, meta=meta)

    @mock.patch('vncdotool.command.vncdo')
    def test_password_forwarded_when_given(self, vncdo) -> None:
        self.options.password = 'secret'
        capture = self.make_capture(session_vdo=b'key a\n')

        command._replay_client(self.op, self.options, capture, 'archive.zip', [])

        argv = vncdo.call_args.args[0]
        assert argv[:4] == ['-s', '127.0.0.1::5999', '-p', 'secret']

    @mock.patch('vncdotool.command.vncdo')
    def test_no_password_option_omits_flag(self, vncdo) -> None:
        capture = self.make_capture(session_vdo=b'key a\n')

        command._replay_client(self.op, self.options, capture, 'archive.zip', [])

        argv = vncdo.call_args.args[0]
        assert '-p' not in argv

    @mock.patch('vncdotool.command.vncdo')
    def test_script_written_passed_and_cleaned_up(self, vncdo) -> None:
        capture = self.make_capture(session_vdo=b'key a\n')

        command._replay_client(self.op, self.options, capture, 'archive.zip', [])

        argv = vncdo.call_args.args[0]
        script = argv[-1]
        assert os.path.basename(script) == 'session.vdo'
        assert not os.path.exists(script), "TemporaryDirectory should clean up its workdir"

    @mock.patch('vncdotool.command.vncdo')
    def test_extra_commands_appended_without_script_when_session_empty(self, vncdo) -> None:
        capture = self.make_capture(session_vdo=b'   \n')

        command._replay_client(self.op, self.options, capture, 'archive.zip', ['key', 'a'])

        argv = vncdo.call_args.args[0]
        assert argv == ['-s', '127.0.0.1::5999', 'key', 'a']

    @mock.patch('vncdotool.command.vncdo')
    def test_no_session_and_no_extra_is_a_usage_error(self, vncdo) -> None:
        capture = self.make_capture(session_vdo=b'')

        command._replay_client(self.op, self.options, capture, 'archive.zip', [])

        assert self.op.error.called
        assert 'archive.zip' in self.op.error.call_args.args[0]

    @mock.patch('vncdotool.command.log')
    @mock.patch('vncdotool.command.vncdo')
    def test_auth_preserved_warns_in_client_mode(self, vncdo, log) -> None:
        capture = self.make_capture(session_vdo=b'key a\n', auth_preserved=True)

        command._replay_client(self.op, self.options, capture, 'archive.zip', [])

        assert log.warning.called
        args = log.warning.call_args.args
        message = args[0] % args[1:]
        assert '-p' in message or 'password' in message

    @mock.patch('vncdotool.command.log')
    @mock.patch('vncdotool.command.vncdo')
    def test_auth_not_preserved_does_not_warn(self, vncdo, log) -> None:
        capture = self.make_capture(session_vdo=b'key a\n', auth_preserved=False)

        command._replay_client(self.op, self.options, capture, 'archive.zip', [])

        assert not log.warning.called


class CLIParsingTestCase(unittest.TestCase):
    """Base for tests that watch what a parser produced.

    Every entry point ends in sys.exit(), so the helpers swallow SystemExit
    and report the parse. The reactor is a stand-in throughout: no test here
    may start one.
    """

    def patch(self, target, *args, **kwargs):
        patcher = mock.patch(target, *args, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def setUp(self) -> None:
        super().setUp()
        self.patch('vncdotool.command.reactor', new_callable=mock.MagicMock)
        self.patch('vncdotool.command.setup_logging')

    def assertUsageError(self, call) -> str:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                call()
        assert raised.exception.code == command.ExitStatus.USAGE, stderr.getvalue()
        return stderr.getvalue()


class TestVncdoArgumentParsing(CLIParsingTestCase):
    """Where `vncdo` stops reading options and starts reading commands.

    The trailing command list may hold anything a command takes -- negative
    coordinates, a bare `-`, a word starting with `--` -- so the boundary is
    part of the CLI contract rather than an accident of the parser.
    """

    def setUp(self) -> None:
        super().setUp()
        self.build_tool = self.patch('vncdotool.command.build_tool')

    def parse(self, argv):
        with self.assertRaises(SystemExit):
            command.vncdo(argv)
        return self.build_tool.call_args.args

    def usage_error(self, argv) -> str:
        return self.assertUsageError(lambda: command.vncdo(argv))

    def output_of(self, argv) -> str:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as raised:
                command.vncdo(argv)
        assert raised.exception.code == 0
        return stdout.getvalue()

    def test_commands_reach_build_tool(self) -> None:
        options, args = self.parse(['key', 'ctrl-c'])
        assert args == ['key', 'ctrl-c']

    def test_options_before_the_commands_are_parsed(self) -> None:
        options, args = self.parse(['-v', '-v', '-s', '1.2.3.4', 'key', 'a'])
        assert options.verbose == 2
        assert options.server == '1.2.3.4'
        assert args == ['key', 'a']

    def test_options_after_the_first_command_are_command_arguments(self) -> None:
        options, args = self.parse(['key', 'a', '-v'])
        assert args == ['key', 'a', '-v']
        assert options.verbose == 0

    def test_double_dash_is_dropped_before_the_command_list(self) -> None:
        options, args = self.parse(['-v', '--', 'key', 'a'])
        assert args == ['key', 'a']

    def test_double_dash_after_a_command_is_a_command_argument(self) -> None:
        options, args = self.parse(['key', '--', 'a'])
        assert args == ['key', '--', 'a']

    def test_negative_coordinates_are_command_arguments(self) -> None:
        options, args = self.parse(['move', '-10', '20'])
        assert args == ['move', '-10', '20']

    def test_a_bare_dash_names_stdin(self) -> None:
        options, args = self.parse(['-'])
        assert args == ['-']

    def test_password_short_and_long(self) -> None:
        for argv in (['-p', 'sekrit', 'key', 'a'], ['--password', 'sekrit', 'key', 'a']):
            self.build_tool.reset_mock()
            options, args = self.parse(argv)
            assert options.password == 'sekrit'
            assert args == ['key', 'a']

    def test_a_password_starting_with_a_dash_needs_the_attached_form(self) -> None:
        """optparse took `-p -dash`; argparse reads a separate argument that
        looks like an option as one, so the value has to be attached."""
        for argv in (['-p-dash', 'key', 'a'], ['--password=-dash', 'key', 'a']):
            self.build_tool.reset_mock()
            options, args = self.parse(argv)
            assert options.password == '-dash', argv
            assert args == ['key', 'a']

        assert '--password' in self.usage_error(['-p', '-dash', 'key', 'a'])

    def test_a_password_that_is_a_negative_number(self) -> None:
        options, args = self.parse(['-p', '-123', 'key', 'a'])
        assert options.password == '-123'

    def test_numeric_options_are_converted(self) -> None:
        options, args = self.parse(['--delay', '25', '-w', '2.5', '-t', '1.5', 'key', 'a'])
        assert options.delay == 25
        assert options.warp == 2.5
        assert options.timeout == 1.5

    def test_the_delay_default_comes_from_the_environment(self) -> None:
        with mock.patch.dict(os.environ, {'VNCDOTOOL_DELAY': '25'}):
            options, args = self.parse(['key', 'a'])
        assert options.delay == 25

    def test_server_defaults_to_loopback(self) -> None:
        options, args = self.parse(['key', 'a'])
        assert options.server == '127.0.0.1'

    def test_flags_default_off(self) -> None:
        options, args = self.parse(['key', 'a'])
        assert not options.force_caps
        assert not options.localcursor
        assert not options.nocursor
        assert not options.disable_desktop_resizing
        assert not options.incremental_refreshes

    def test_no_command_is_a_usage_error(self) -> None:
        assert 'no command provided' in self.usage_error([])

    def test_unknown_option_is_a_usage_error(self) -> None:
        assert '--nope' in self.usage_error(['--nope', 'key', 'a'])

    def test_a_non_numeric_delay_is_a_usage_error(self) -> None:
        assert '--delay' in self.usage_error(['--delay', 'soon', 'key', 'a'])

    def test_an_unknown_pixel_format_is_a_usage_error(self) -> None:
        assert 'rgb999' in self.usage_error(['--pixel-format', 'rgb999', 'key', 'a'])

    def test_help_lists_the_command_vocabulary(self) -> None:
        help_text = self.output_of(['--help'])
        assert 'Common Commands (CMD):' in help_text
        assert 'key KEY' in help_text
        assert 'rstable SECONDS X Y W H [FUZZ]' in help_text

    def test_help_expands_every_placeholder(self) -> None:
        help_text = self.output_of(['--help'])
        assert '[options] CMD CMDARGS|-|filename' in help_text
        for unexpanded in ('%prog', '%default', '%(prog)s', '%(default)s'):
            assert unexpanded not in help_text, unexpanded

    def test_version_is_reported(self) -> None:
        from vncdotool import __version__
        assert __version__ in self.output_of(['--version'])


class TestVnclogArgumentParsing(CLIParsingTestCase):
    """`vnclog`'s option checks, including the ones that turn a ValueError
    from check_capture_target into a usage error."""

    def setUp(self) -> None:
        super().setUp()
        self.build_proxy = self.patch('vncdotool.command.build_proxy')
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name

    def parse(self, argv):
        self.patch('sys.argv', ['vnclog'] + argv)
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                command.vnclog()
        return self.build_proxy.call_args.args[0]

    def usage_error(self, argv) -> str:
        self.patch('sys.argv', ['vnclog'] + argv)
        return self.assertUsageError(command.vnclog)

    def test_output_and_options_reach_the_proxy(self) -> None:
        options = self.parse(['--listen', '5910', '-s', '1.2.3.4', '-'])
        assert options.listen == 5910
        assert options.host == '1.2.3.4'

    def test_missing_output_is_a_usage_error(self) -> None:
        assert 'incorrect number of arguments' in self.usage_error([])

    def test_a_second_output_is_a_usage_error(self) -> None:
        assert 'incorrect number of arguments' in self.usage_error(['one.vdo', 'two.vdo'])

    def test_capture_raw_target_must_end_in_zip(self) -> None:
        target = os.path.join(self.tmp, 'capture.tar')
        assert 'must end in .zip' in self.usage_error(['--capture-raw', target])

    def test_capture_raw_target_directory_must_exist(self) -> None:
        target = os.path.join(self.tmp, 'nowhere', 'capture.zip')
        assert 'does not exist' in self.usage_error(['--capture-raw', target])

    def test_capture_raw_takes_no_output(self) -> None:
        target = os.path.join(self.tmp, 'capture.zip')
        assert 'OUTPUT is implied' in self.usage_error(['--capture-raw', target, 'out.vdo'])

    def test_one_shot_and_file_per_client_conflict(self) -> None:
        assert '--file-per-client' in self.usage_error(['--one-shot', '--file-per-client', 'out'])

    def test_capture_raw_unsafe_alone_is_a_usage_error(self) -> None:
        assert '--capture-raw-unsafe' in self.usage_error(['--capture-raw-unsafe', 'out.vdo'])

    def test_a_non_numeric_listen_port_is_a_usage_error(self) -> None:
        assert '--listen' in self.usage_error(['--listen', 'soon', 'out.vdo'])


class TestVncdoReplayArgumentParsing(CLIParsingTestCase):
    """`vncdo-replay` reads options on either side of the archive, but the
    command list has to run straight on from it: the functional suite starts
    it as `--server ARCHIVE --listen PORT --forever`, and docs/capture.md
    drives it as `ARCHIVE CMD ARGS...`."""

    def setUp(self) -> None:
        super().setUp()
        self.capture = Capture(s2c=b'', session_vdo=b'key a\n', meta=None)
        self.patch('vncdotool.replay.load_capture', return_value=self.capture)
        self.factory = self.patch('vncdotool.replay.ReplayFactory')
        self.replay_client = self.patch('vncdotool.command._replay_client')

    def run_replay(self, argv) -> None:
        self.patch('sys.argv', ['vncdo-replay'] + argv)
        command.vncdo_replay()

    def usage_error(self, argv) -> str:
        self.patch('sys.argv', ['vncdo-replay'] + argv)
        return self.assertUsageError(command.vncdo_replay)

    def test_server_options_follow_the_archive(self) -> None:
        self.run_replay(['--server', 'capture.zip', '--listen', '5999', '--forever'])
        options = self.factory.call_args.kwargs
        assert options['forever'] is True
        assert command.reactor.listenTCP.call_args.args[0] == 5999

    def test_commands_follow_the_archive(self) -> None:
        self.run_replay(['-s', '127.0.0.1::5999', 'capture.zip', 'capture', 'out.png'])
        archive, extra = self.replay_client.call_args.args[3:]
        assert archive == 'capture.zip'
        assert extra == ['capture', 'out.png']

    def test_an_option_between_the_archive_and_the_commands_is_a_usage_error(self) -> None:
        """optparse read the commands past the option; argparse matches one
        contiguous run of positionals, so the commands go unmatched."""
        assert 'unrecognized arguments: capture out.png' in self.usage_error(
            ['capture.zip', '-v', 'capture', 'out.png']
        )

    def test_no_archive_is_a_usage_error(self) -> None:
        assert 'no capture archive' in self.usage_error([])

    def test_server_mode_refuses_commands(self) -> None:
        assert 'takes no commands' in self.usage_error(['--server', 'capture.zip', 'key', 'a'])
