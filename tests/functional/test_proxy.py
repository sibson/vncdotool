from unittest import TestCase
import sys

import pexpect

from vncdotool import rfb


class TestLogEvents(TestCase):
    def setUp(self):
        cmd = 'vncev -rfbport 5999 -rfbwait 1000'
        self.server = pexpect.spawn(cmd, timeout=2)
        self.server.logfile_read = sys.stdout

        cmd = 'vnclog --listen 1842 -s :99 -'
        self.recorder = pexpect.spawn(cmd, timeout=2)
        self.recorder.logfile_read = sys.stdout

    def tearDown(self):
        self.server.terminate(force=True)
        if self.recorder:
            self.recorder.terminate(force=True)

    def run_vncdo(self, commands):
        cmd = 'vncdo -s localhost::1842 ' + commands
        vnc = pexpect.spawn(cmd, timeout=2)
        vnc.logfile_read = sys.stdout
        retval = vnc.wait()
        assert retval == 0, (retval, str(vnc))

    def assertKeyDown(self, key):
        down = '^.*down:\s+\(%s\)\r' % hex(key)
        self.server.expect(down)

    def assertKeyUp(self, key):
        up = '^.*up:\s+\(%s\)\r'  % hex(key)
        self.server.expect(up)

    def assertMouse(self, x, y, buttonmask):
        output = '^.*Ptr: mouse button mask %s at %d,%d' % (hex(buttonmask), x, y)
        self.server.expect(output)

    def test_key_alpha(self):
        self.run_vncdo('key z')

        self.assertKeyDown(ord('z'))
        self.assertKeyUp(ord('z'))

        self.recorder.expect('keydown z')
        self.recorder.expect('keyup z')

    def test_key_ctrl_a(self):
        self.run_vncdo('key ctrl-a')
        self.assertKeyDown(rfb.KEY_ControlLeft)
        self.assertKeyDown(ord('a'))
        self.assertKeyUp(rfb.KEY_ControlLeft)
        self.assertKeyUp(ord('a'))

    def test_mouse(self):
        self.run_vncdo('move 111 222 click 1')
        self.assertMouse(111, 222, 1)
        self.recorder.expect('move 111 222')
        self.recorder.expect('click 1')
