import shlex
import sys
from unittest import TestCase

import pexpect

from vncdotool import rfb

from .cli import spawn_command
from .libvncserver import example_command


class TestLogEvents(TestCase):
    def setUp(self) -> None:
        server_cmd, server_args, server_env = example_command(
            "vncev", "-rfbport", "5999", "-rfbwait", "1000"
        )
        self.server = pexpect.spawn(server_cmd, list(server_args), env=server_env, timeout=5)
        self.server.logfile_read = sys.stdout.buffer
        self.server.expect('Listening for VNC connections on TCP port')

        self.recorder = spawn_command(
            "vnclog", "--listen", "1842", "-s", ":99", "-", timeout=5
        )
        self.recorder.logfile_read = sys.stdout.buffer

    def tearDown(self) -> None:
        self.server.terminate(force=True)
        if self.recorder:
            self.recorder.terminate(force=True)

    def run_vncdo(self, commands: str) -> None:
        args = shlex.split(commands)
        vnc = spawn_command("vncdo", "-s", "localhost::1842", *args, timeout=5)
        vnc.logfile_read = sys.stdout.buffer
        retval = vnc.wait()
        assert retval == 0, (retval, str(vnc))

    def assertKeyDown(self, key: int) -> None:
        down = rf'^.*down:\s+\({key:#x}\)\r'
        self.server.expect(down)

    def assertKeyUp(self, key: int) -> None:
        up = rf'^.*up:\s+\({key:#x}\)\r'
        self.server.expect(up)

    def assertMouse(self, x: int, y: int, buttonmask: int) -> None:
        output = f'^.*Ptr: mouse button mask {buttonmask:#x} at {x},{y}'
        self.server.expect(output)

    def test_key_alpha(self) -> None:
        self.run_vncdo('key z')

        self.assertKeyDown(ord('z'))
        self.assertKeyUp(ord('z'))

        self.recorder.expect('keydown z')
        self.recorder.expect('keyup z')

    def test_key_ctrl_a(self) -> None:
        self.run_vncdo('key ctrl-a')
        self.assertKeyDown(rfb.KEY_ControlLeft)
        self.assertKeyDown(ord('a'))
        self.assertKeyUp(ord('a'))
        self.assertKeyUp(rfb.KEY_ControlLeft)

    def test_mouse(self) -> None:
        self.run_vncdo('move 111 222 click 1')
        self.assertMouse(111, 222, 1)
        self.recorder.expect('move 111 222')
        self.recorder.expect('click 1')
