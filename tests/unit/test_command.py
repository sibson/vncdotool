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
from vncdotool.client import AuthenticationError, ProtocolError
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
    """vncdo(argv) must feed optparse instead of mutating sys.argv, so a
    caller like _replay_client can build a synthetic invocation directly."""

    def test_argv_parameter_is_what_gets_parsed(self, reactor, connect) -> None:
        with self.assertRaises(SystemExit) as raised:
            command.vncdo(['nosuchcommand'])

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
