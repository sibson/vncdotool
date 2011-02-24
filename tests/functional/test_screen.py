import pexpect
import sys
import os.path

DATADIR = os.path.join(os.path.dirname(__file__), 'data')


class TestVNCCapture(object):

    def tearDown(self):
        self.server.terminate(force=True)

    def run_server(self, server):
        cmd = '%s -rfbport 5910 -rfbwait 1000' % server
        self.server = pexpect.spawn(cmd, timeout=2)
        self.server.logfile_read = sys.stdout

    def run_vncdotool(self, commands, exitcode=0):
        cmd = 'vncdotool -d 10 ' + commands
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
        fname = 'test_capture_example.png'
        self.run_server('example')
        self.run_vncdotool('capture %s' % fname)
        self.assertFilesEqual(fname, os.path.join(DATADIR, 'example.png'))

    def testExpectExampleExactly(self):
        self.run_server('example')
        self.run_vncdotool('expect %s 0' % os.path.join(DATADIR, 'example.png'))

    def testExpectExampleSloppy(self):
        self.run_server('example')
        example = os.path.join(DATADIR, 'example.png')
        self.run_vncdotool('move 30 20 expect %s 20' % example)

    def testExpectFailsExample(self):
        self.run_server('example')
        simple = os.path.join(DATADIR, 'simple.png')
        try:
            self.run_vncdotool('expect %s 0' % simple, exitcode=10)
        except pexpect.TIMEOUT:
            pass
        else:
            raise AssertionError('should timeout')
