from unittest import TestCase
import sys
import os.path
import tempfile

import pexpect


DATADIR = os.path.join(os.path.dirname(__file__), 'data')
SIMPLE_PNG  = os.path.join(DATADIR, 'simple.png')
EXAMPLE_PNG = os.path.join(DATADIR, 'example.png')
EXAMPLE_NOCURSOR_PNG = os.path.join(DATADIR, 'example_nocursor.png')


class TestVNCCapture(TestCase):
    server = None

    def setUp(self):
        self.tempfiles = []

    def tearDown(self):
        if self.server:
            self.server.terminate(force=True)

        for f in self.tempfiles:
            os.remove(f.name)

    def mktemp(self):
        f = tempfile.NamedTemporaryFile(suffix='.png')
        self.tempfiles.append(f)
        f.close()
        return f.name

    def run_server(self, server):
        cmd = '%s -rfbport 5910 -rfbwait 1000' % server
        self.server = pexpect.spawn(cmd, timeout=2)
        self.server.logfile_read = sys.stdout

    def run_vncdo(self, commands, exitcode=0):
        cmd = 'vncdo -s :10 ' + commands
        vnc = pexpect.spawn(cmd, logfile=sys.stdout, timeout=5)
        vnc.logfile_read = sys.stdout
        vnc.expect(pexpect.EOF)
        if vnc.isalive():
            vnc.wait()

        assert vnc.exitstatus == exitcode, vnc.exitstatus

    def assertFilesEqual(self, filename, othername):
        content = open(filename, 'rb').read()
        othercontent = open(othername, 'rb').read()

        assert content == othercontent

    def testCaptureExample(self):
        fname = self.mktemp()
        self.run_server('example')
        self.run_vncdo('move 150 100 capture %s' % fname)
        self.assertFilesEqual(fname, EXAMPLE_PNG)

    def testCaptureCapture(self):
        f1 = self.mktemp()
        f2 = self.mktemp()

        self.run_server('example')
        self.run_vncdo('move 150 100 capture %s capture %s' % (f1, f2))
        self.assertFilesEqual(f1, EXAMPLE_PNG)
        self.assertFilesEqual(f2, f1)

    def testCaptureNoCursor(self):
        fname = self.mktemp()
        self.run_server('example')
        self.run_vncdo('--nocursor move 150 100 pause 0.1 capture %s' % fname)
        self.assertFilesEqual(fname, EXAMPLE_NOCURSOR_PNG)

    def testCaptureLocalCursor(self):
        fname = self.mktemp()
        self.run_server('example')
        self.run_vncdo('--localcursor move 150 100 pause 0.1 capture %s' % fname)
        self.assertFilesEqual(fname, EXAMPLE_PNG)

    def testExpectExampleExactly(self):
        self.run_server('example')
        self.run_vncdo('move 150 100 pause 0.1 expect %s 0' % EXAMPLE_PNG)

    def testExpectExampleSloppy(self):
        self.run_server('example')
        self.run_vncdo('move 200 100 expect %s 25' % EXAMPLE_PNG)

    def testExpectFailsExample(self):
        self.run_server('example')
        try:
            self.run_vncdo('expect %s 0' % SIMPLE_PNG, exitcode=10)
        except pexpect.TIMEOUT:
            pass
        else:
            raise AssertionError('should timeout')
