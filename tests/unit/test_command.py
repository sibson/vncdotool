
from vncdotool import command
import mock

 
@mock.isolate(command.build_command_list)
class TestBuildCommandList(object):
    def setUp(self):
        self.factory = mock.Mock()
        self.client = command.VNCDoToolClient
        self.deferred = self.factory.deferred

    def assertCalled(self, fn, *args):
        self.deferred.addCallback.assert_called_once_with(fn, *args)

    def call_build_commands_list(self, commands):
        command.build_command_list(self.factory, commands.split()) 

    def test_alphanum_key(self):
        self.call_build_commands_list('key a')
        self.assertCalled(self.client.keyPress, 'a')

    def test_control_key(self):
        self.call_build_commands_list('key ctrl-c')
        self.assertCalled(self.client.keyPress, 'ctrl-c')

    def test_key_missing(self):
        pass

    def test_move(self):
        self.call_build_commands_list('move 100 200')
        self.assertCalled(self.client.mouseMove, 100, 200)

    def test_move_missing(self):
        pass

    def test_click(self):
        self.call_build_commands_list('click 1')
        self.assertCalled(self.client.mousePress, 1)

    def test_click_missing(self):
        pass

    def test_type(self):
        self.call_build_commands_list('type foobar')
        call = self.factory.deferred.addCallback
        for key in 'foobar':
            call.assert_calls_exist_with(self.client.keyPress, key)

    def test_type_missing(self):
        pass

    def test_capture(self):
        self.call_build_commands_list('capture foo.png')
        self.assertCalled(self.client.captureScreen, 'foo.png')

    def test_capture_not_png(self):
        pass

    def test_capture_missing(self):
        pass

    def test_expect(self):
        self.call_build_commands_list('expect foo.png 10')
        self.assertCalled(self.client.expectScreen, 'foo.png', 10)

    def test_expect_not_png(self):
        pass

    def test_expect_missing(self):
        pass

    def test_chain_key_commands(self):
        self.call_build_commands_list('type foobar key enter')
        call = self.factory.deferred.addCallback
        for key in 'foobar':
            call.assert_calls_exist_with(self.client.keyPress, key)
        call.assert_calls_exist_with(self.client.keyPress, 'enter')

    def test_chain_type_expect(self):
        self.call_build_commands_list('type username expect password.png 0')
        call = self.factory.deferred.addCallback
        for key in 'username':
            call.assert_calls_exist_with(self.client.keyPress, key)

        call.assert_calls_exist_with(self.client.expectScreen, 'password.png', 0)



@mock.isolate(command.main)
class TestMain(object):
    def setUp(self):
        self.factory = command.VNCDoToolFactory.return_value
        self.options = mock.Mock()
        self.options.display = 0
        self.options.server = '127.0.0.1'
        parse_args = command.VNCDoToolOptionParser.return_value.parse_args
        parse_args.return_value = (self.options, [])

    def test_single_host_name(self):
        self.options.server = '10.11.12.13'
        command.main()
        connectTCP = command.reactor.connectTCP
        connectTCP.assert_called_once_with('10.11.12.13', 5900, self.factory)
    def test_host_port(self):
        self.options.server = '10.11.12.13:4444'
        command.main()
        connectTCP = command.reactor.connectTCP
        connectTCP.assert_called_once_with('10.11.12.13', 4444, self.factory)
    def test_localhost_display(self):
        self.options.display = 10
        command.main()
        connectTCP = command.reactor.connectTCP
        connectTCP.assert_called_once_with('127.0.0.1', 5910, self.factory)

    def test_host_display(self):
        self.options.server = '10.11.12.13'
        self.options.display = 10
        command.main()
        connectTCP = command.reactor.connectTCP
        connectTCP.assert_called_once_with('10.11.12.13', 5910, self.factory)
    def test_host_default(self):
        command.main()
        connectTCP = command.reactor.connectTCP
        connectTCP.assert_called_once_with('127.0.0.1', 5900, self.factory)

    def test_password(self):
        self.options.password = 'openseseame'
        command.main()
        assert self.factory.password == 'openseseame'
