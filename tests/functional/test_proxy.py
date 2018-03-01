from unittest import TestCase
import sys

import pexpect

from vncdotool import rfb
from helpers import PExpectAssertMixin


class TestLogEvents(PExpectAssertMixin, TestCase):
    def setUp(self):
        cmd = u'vncev -rfbport 5999 -rfbwait 1000'
        self.server = pexpect.spawn(cmd, logfile=sys.stdout, timeout=10)

        cmd = u'vnclog --listen 1842 -s :99 -'
        self.recorder = pexpect.spawn(cmd, logfile=sys.stdout, timeout=10)

    def tearDown(self):
        self.server.terminate(force=True)
        if self.recorder:
            self.recorder.terminate(force=True)

    def run_vncdo(self, commands):
        cmd = u'vncdo -s localhost::1842 ' + commands
        vnc = pexpect.spawn(cmd, logfile=sys.stdout, timeout=2)
        retval = vnc.wait()
        assert retval == 0, (retval, str(vnc))

    def test_key_alpha(self):
        self.run_vncdo(u'key z')

        self.assertKeyDown(ord('z'))
        self.assertKeyUp(ord('z'))

        self.recorder.expect(u'keydown z')
        self.recorder.expect(u'keyup z')

    def test_key_ctrl_a(self):
        self.run_vncdo(u'key ctrl-a')
        self.assertKeyDown(rfb.KEY_ControlLeft)
        self.assertKeyDown(ord('a'))
        self.assertKeyUp(rfb.KEY_ControlLeft)
        self.assertKeyUp(ord('a'))

    def test_mouse(self):
        self.run_vncdo(u'move 111 222 click 1')
        self.assertMouse(111, 222, 1)
        self.recorder.expect(u'move 111 222')
        self.recorder.expect(u'click 1')
