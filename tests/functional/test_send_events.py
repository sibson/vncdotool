import os.path
import shlex
import sys
from unittest import TestCase

import pexpect

DATADIR = os.path.join(os.path.dirname(__file__), 'data')
KEYA_VDO = os.path.join(DATADIR, 'samplea.vdo')
KEYB_VDO = os.path.join(DATADIR, 'sampleb.vdo')


from .cli import spawn_command
from .libvncserver import example_command


class TestSendEvents(TestCase):

    def setUp(self) -> None:
        server_cmd, server_args, server_env = example_command(
            'vncev', '-rfbport', '5933', '-rfbwait', '1000'
        )
        self.server = pexpect.spawn(
            server_cmd,
            list(server_args),
            logfile=sys.stdout.buffer,
            env=server_env,
            timeout=5,
        )
        self.server.logfile_read = sys.stdout.buffer
        self.server.expect('Listening for VNC connections on TCP port')

    def tearDown(self) -> None:
        self.server.terminate(force=True)

    def assertKeyDown(self, key: int) -> None:
        down = rf'^.*down:\s+\({key:#x}\)\r'
        self.server.expect(down)

    def assertKeyUp(self, key: int) -> None:
        up = rf'^.*up:\s+\({key:#x}\)\r'
        self.server.expect(up)

    def assertMouse(self, x: int, y: int, buttonmask: int) -> None:
        output = f'^.*Ptr: mouse button mask {buttonmask:#x} at {x},{y}'
        self.server.expect(output)

    def assertDisconnect(self) -> None:
        disco = 'Client 127.0.0.1 gone'
        self.server.expect(disco)

    def run_vncdo(self, commands: str) -> None:
        args = shlex.split(commands)
        vnc = spawn_command(
            'vncdo', '-v', '-s', ':33', *args, logfile=sys.stdout.buffer, timeout=5
        )
        retval = vnc.wait()
        assert retval == 0, retval

    def test_key_alpha(self) -> None:
        self.run_vncdo('key z')
        self.assertKeyDown(ord('z'))
        self.assertKeyUp(ord('z'))
        self.assertDisconnect()

    def test_key_ctrl_a(self) -> None:
        self.run_vncdo('key ctrl-a')
        self.assertKeyDown(int(0xffe3))
        self.assertKeyDown(ord('a'))
        self.assertKeyUp(ord('a'))
        self.assertKeyUp(int(0xffe3))
        self.assertDisconnect()

    def test_type(self) -> None:
        string = 'abcdefghij'
        self.run_vncdo(f'type {string}')
        for key in string:
            self.assertKeyDown(ord(key))
            self.assertKeyUp(ord(key))
        self.assertDisconnect()

    def test_mouse_move(self) -> None:
        self.run_vncdo('move 10 20 click 1')
        self.assertMouse(10, 20, 0x1)
        self.assertDisconnect()

    def test_mouse_drag(self) -> None:
        self.run_vncdo('move 10 20 drag 30 30 click 1')
        self.assertMouse(10, 20, 0x0)
        self.assertMouse(20, 25, 0x0)
        self.assertMouse(30, 30, 0x1)
        self.assertDisconnect()

    def test_mouse_click_button_two(self) -> None:
        self.run_vncdo('click 2')
        self.assertMouse(0, 0, 0x2)
        self.assertDisconnect()

    def test_read_files(self) -> None:
        self.run_vncdo(f'key x {KEYA_VDO} key y {KEYB_VDO}')
        for key in 'xayb':
            self.assertKeyDown(ord(key))
            self.assertKeyUp(ord(key))
