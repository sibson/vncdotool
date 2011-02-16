import pexpect
import unittest
import sys


class TestSendEvents(object):

    def setUp(self):
        cmd = 'vncev -rfbport 5910 -rfbwait 1000'
        self.server = pexpect.spawn(cmd, timeout=2)
        self.server.logfile_read = sys.stdout

    def tearDown(self):
        self.server.terminate(force=True)

    def assertKeyDown(self, key):
        down = '^.*down:\s+\(%s\)\r' % hex(key)
        self.server.expect(down)

    def assertKeyUp(self, key):
        up = '^.*up:\s+\(%s\)\r'  % hex(key)
        self.server.expect(up)

    def assertMouse(self, x, y, buttonmask):
        output = '^.*Ptr: mouse button mask %s at %d,%d' % (hex(buttonmask), x, y)
        self.server.expect(output)

    def assertDisconnect(self):
        disco = 'Client 127.0.0.1 gone'
        self.server.expect(disco)

    def run_vncdotool(self, commands):
        cmd = 'vncdotool -d 10 ' + commands
        vnc = pexpect.spawn(cmd, logfile=sys.stdout, timeout=5)
        retval = vnc.wait()
        assert retval == 0, retval

        
    def test_key_alpha(self):
        self.run_vncdotool('key z')
        self.assertKeyDown(ord('z'))
        self.assertKeyUp(ord('z'))
        self.assertDisconnect()
    
    def test_key_ctrl_a(self):
        self.run_vncdotool('key ctrl-a')
        self.assertKeyDown(int(0xffe3))
        self.assertKeyDown(ord('a'))
        self.assertKeyUp(int(0xffe3))
        self.assertKeyUp(ord('a'))
        self.assertDisconnect()

    def test_type(self):
        string = 'abcdefghij'
        self.run_vncdotool('type %s' % string)
        for key in string:
            self.assertKeyDown(ord(key))
            self.assertKeyUp(ord(key))
        self.assertDisconnect()

    def test_mouse_move(self):
        return "vncev doesn't seem to support move"
        self.run_vncdotool('move 10 20')
        self.assertMouse(10, 20, 0)
        self.assertDisconnect()

    def test_mouse_button_two(self):
        self.run_vncdotool('click 2')
        self.assertMouse(0, 0, 0x4)
        self.assertDisconnect()
