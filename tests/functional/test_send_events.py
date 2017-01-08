from unittest import TestCase
import sys
import os.path

import pexpect

from helpers import PExpectAssertMixin

DATADIR = os.path.join(os.path.dirname(__file__), 'data')
KEYA_VDO = os.path.join(DATADIR, 'samplea.vdo')
KEYB_VDO = os.path.join(DATADIR, 'sampleb.vdo')


class TestSendEvents(PExpectAssertMixin, TestCase):

    def setUp(self):
        cmd = u'vncev -rfbport 5933 -rfbwait 1000'
        self.server = pexpect.spawn(cmd, logfile=sys.stdout, timeout=2)

    def tearDown(self):
        self.server.terminate(force=True)

    def run_vncdo(self, commands):
        cmd = u'vncdo -v -s :33 ' + commands
        vnc = pexpect.spawn(cmd, logfile=sys.stdout, timeout=5)
        retval = vnc.wait()
        assert retval == 0, retval

    def test_key_alpha(self):
        self.run_vncdo(u'key z')
        self.assertKeyDown(ord('z'))
        self.assertKeyUp(ord('z'))
        self.assertDisconnect()

    def test_key_ctrl_a(self):
        self.run_vncdo(u'key ctrl-a')
        self.assertKeyDown(int(0xffe3))
        self.assertKeyDown(ord('a'))
        self.assertKeyUp(int(0xffe3))
        self.assertKeyUp(ord('a'))
        self.assertDisconnect()

    def test_type(self):
        string = u'abcdefghij'
        self.run_vncdo(u'type %s' % string)
        for key in string:
            self.assertKeyDown(ord(key))
            self.assertKeyUp(ord(key))
        self.assertDisconnect()

    def test_mouse_move(self):
        # vncev only prints click events, but will include the position
        self.run_vncdo(u'move 10 20 click 1')
        self.assertMouse(10, 20, 0x1)
        self.assertDisconnect()

    def test_mouse_click_button_two(self):
        self.run_vncdo(u'click 2')
        self.assertMouse(0, 0, 0x2)
        self.assertDisconnect()

    def test_read_files(self):
        self.run_vncdo(u'key x %s key y %s' % (KEYA_VDO, KEYB_VDO))
        for key in 'xayb':
            self.assertKeyDown(ord(key))
            self.assertKeyUp(ord(key))
