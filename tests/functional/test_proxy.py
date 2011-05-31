import pexpect
import unittest
import sys

class TestLogEvents(object):
    def setUp(self):
        cmd = 'vncev -rfbport 5910 -rfbwait 1000'
        self.server = pexpect.spawn(cmd, timeout=2)
        self.server.logfile_read = sys.stdout
        cmd = 'vncdotool -d 10 proxy 6000'
        self.logger = pexpect.spawn(cmd, timeout=2)
        self.logger.logfile_read = sys.stdout

    def tearDown(self):
        self.server.terminate(force=True)
        if self.logger:
            self.logger.terminate(force=True)

    def run_vncdotool(self, commands):
        cmd = 'vncdotool -s localhost:6000 ' + commands
        vnc = pexpect.spawn(cmd, logfile=sys.stdout, timeout=2)
        retval = vnc.wait()
        assert retval == 0, retval

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
        self.logger.expect('key z')

    def test_key_ctrl_a(self):
        # XXX not supported
        pass

    def test_mouse(self):
        self.run_vncdotool('move 111 222 click 1')
        self.assertMouse(111, 222, 1)
        self.logger.expect('move 111 222')
        self.logger.expect('click 1')
