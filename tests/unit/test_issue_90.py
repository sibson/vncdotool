import unittest
from struct import pack
from unittest import TestCase, mock

from vncdotool import client


class TestIssue90(TestCase):
    """captureScreen saves an all-black image when the first framebuffer
    update contains only a PSEUDO_DESKTOP_SIZE rectangle (TightVNC does this).

    https://github.com/sibson/vncdotool/issues/90

    Expected: a non-incremental refresh completes only once pixel data arrives.
    Actual:   updateDesktopSize creates a black canvas, commitUpdate fires the
              capture deferred, and the black canvas is what gets saved.

    A wire-level reproduction (real vncdo CLI against a server replaying the
    TightVNC behaviour from the issue's logs) lives in tests/triage/issue_90/.

    TRIAGE ARTIFACT -- this file and tests/triage/issue_90/ are temporary.
    When the fix lands, move this test into tests/unit/test_client.py, drop
    the expectedFailure marker, rename it for the behaviour it checks, and
    delete this file and the tests/triage/issue_90/ directory.
    """

    MSG_HANDSHAKE = b"RFB 003.003\n"
    MSG_INIT = (
        b"\x00\x00"  # width
        b"\x00\x00"  # height
        b"\x20\x18\x00\x01\x00\xff\x00\xff\x00\xff\x00\x08\x10\x00\x00\x00"  # pixel-format
        b"\x00\x00\x00\x00"  # server-name-len
    )
    FBU_DESKTOP_SIZE_ONLY = (
        b"\x00"  # MsgS2C.FRAMEBUFFER_UPDATE
        b"\x00"  # padding
        b"\x00\x01"  # number-of-rectangles = 1
        + pack("!HHHHi", 0, 0, 1920, 1200, -223)  # PSEUDO_DESKTOP_SIZE, no pixel data
    )

    def setUp(self) -> None:
        self.client = client.VNCDoToolClient()
        self.client.transport = mock.Mock()
        self.client.factory = mock.Mock()
        self.client.framebufferUpdateRequest = mock.Mock()  # type: ignore[assignment]
        self.client.setEncodings = mock.Mock()  # type: ignore[assignment]
        self.client._packet = bytearray(self.MSG_HANDSHAKE)
        self.client._handleInitial()
        self.client._handleServerInit(self.MSG_INIT)

    @unittest.expectedFailure
    def test_capture_waits_for_pixel_data_after_desktop_size(self) -> None:
        d = self.client.refreshScreen()
        fired: list = []
        d.addCallback(fired.append)

        self.client.dataReceived(self.FBU_DESKTOP_SIZE_ONLY)

        self.assertEqual(
            fired, [], "refresh completed on a pseudo-rect with no pixel data"
        )
