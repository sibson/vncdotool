import os.path
import sys
import tempfile
from shutil import which
from typing import IO, List, Optional
from unittest import TestCase, skipUnless

import pexpect

DATADIR = os.path.join(os.path.dirname(__file__), 'data')
SIMPLE_PNG = os.path.join(DATADIR, 'simple.png')
EXAMPLE_PNG = os.path.join(DATADIR, 'example.png')
EXAMPLE_NOCURSOR_PNG = os.path.join(DATADIR, 'example_nocursor.png')

SERVER = "example"


@skipUnless(which(SERVER), reason=f"requires program {SERVER!r}")
class TestVNCCapture(TestCase):
    server: Optional[pexpect.spawn] = None

    def setUp(self) -> None:
        self.tempfiles: List[IO[bytes]] = []

    def tearDown(self) -> None:
        if self.server:
            self.server.terminate(force=True)

        for f in self.tempfiles:
            os.remove(f.name)

    def mktemp(self) -> str:
        f = tempfile.NamedTemporaryFile(suffix='.png')
        self.tempfiles.append(f)
        f.close()
        return f.name

    def run_server(self, server: str) -> None:
        cmd = f'{server} -rfbport 5910 -rfbwait 1000'
        self.server = pexpect.spawn(cmd, timeout=2)
        self.server.logfile_read = sys.stdout.buffer

    def run_vncdo(self, commands: str, exitcode: int = 0) -> None:
        cmd = f'vncdo -s :10 {commands}'
        vnc = pexpect.spawn(cmd, logfile=sys.stdout.buffer, timeout=5)
        vnc.logfile_read = sys.stdout.buffer
        vnc.expect(pexpect.EOF)
        if vnc.isalive():
            vnc.wait()

        assert vnc.exitstatus == exitcode, vnc.exitstatus

    def assertFilesEqual(self, filename: str, othername: str) -> None:
        with open(filename, 'rb') as fd:
            content = fd.read()
        with open(othername, 'rb') as fd:
            othercontent = fd.read()

        assert content == othercontent

    def testCaptureExample(self) -> None:
        fname = self.mktemp()
        self.run_server(SERVER)
        self.run_vncdo(f'move 150 100 capture {fname}')
        self.assertFilesEqual(fname, EXAMPLE_PNG)

    def testCaptureCapture(self) -> None:
        f1 = self.mktemp()
        f2 = self.mktemp()

        self.run_server(SERVER)
        self.run_vncdo(f'move 150 100 capture {f1} capture {f2}')
        self.assertFilesEqual(f1, EXAMPLE_PNG)
        self.assertFilesEqual(f2, f1)

    def testCaptureNoCursor(self) -> None:
        fname = self.mktemp()
        self.run_server(SERVER)
        self.run_vncdo(f'--nocursor move 150 100 pause 0.1 capture {fname}')
        self.assertFilesEqual(fname, EXAMPLE_NOCURSOR_PNG)

    def testCaptureLocalCursor(self) -> None:
        fname = self.mktemp()
        self.run_server(SERVER)
        self.run_vncdo(f'--localcursor move 150 100 pause 0.1 capture {fname}')
        self.assertFilesEqual(fname, EXAMPLE_PNG)

    def testExpectExampleExactly(self) -> None:
        self.run_server(SERVER)
        self.run_vncdo(f'move 150 100 pause 0.1 expect {EXAMPLE_PNG} 0')

    def testExpectExampleSloppy(self) -> None:
        self.run_server(SERVER)
        self.run_vncdo(f'move 200 100 expect {EXAMPLE_PNG} 25')

    def testExpectFailsExample(self) -> None:
        self.run_server(SERVER)
        try:
            self.run_vncdo(f'expect {SIMPLE_PNG} 0', exitcode=10)
        except pexpect.TIMEOUT:
            pass
        else:
            raise AssertionError('should timeout')
