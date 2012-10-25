import pexpect
import unittest
import sys
from vncdotool import rfb


class TestLogEvents(object):
    def setUp(self):
        cmd = 'vncev -rfbport 5999 -rfbwait 1000'
        self.server = pexpect.spawn(cmd, timeout=2)
        self.server.logfile_read = sys.stdout

        cmd = 'vncdotool -d 99 record 11842 -'
        self.logger = pexpect.spawn(cmd, timeout=2)
        self.logger.logfile_read = sys.stdout

    def tearDown(self):
        self.server.terminate(force=True)
        if self.logger:
            self.logger.terminate(force=True)

    def run_vncdotool(self, commands):
        cmd = 'vncdotool -s localhost:11842 ' + commands
        vnc = pexpect.spawn(cmd, logfile=sys.stdout, timeout=2)
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
        self.run_vncdotool('key z')

        self.assertKeyDown(ord('z'))
        self.assertKeyUp(ord('z'))

        self.logger.expect('keydown z')
        self.logger.expect('keyup z')

    def test_key_ctrl_a(self):
        self.run_vncdotool('key ctrl-a')
        self.assertKeyDown(rfb.KEY_ControlLeft)
        self.assertKeyDown(ord('a'))
        self.assertKeyUp(rfb.KEY_ControlLeft)
        self.assertKeyUp(ord('a'))

    def test_mouse(self):
        self.run_vncdotool('move 111 222 click 1')
        self.assertMouse(111, 222, 1)
        self.logger.expect('move 111 222')
        self.logger.expect('click 1')
