import unittest
from unittest import TestCase, mock

from vncdotool import rfb


class TestIssue262(TestCase):
    """An RFB 3.8 authentication failure with an empty reason string hangs.

    https://github.com/sibson/vncdotool/issues/262

    Expected: the client reports the failure once and stops parsing.
    Actual:   the parser re-enters the finished security handler forever,
              spinning the reactor thread at 100% CPU, so neither
              `vncdo --timeout` nor `api.connect(timeout=)` can end it.

    TRIAGE ARTIFACT -- this file is temporary. When the fix lands, move this
    test into tests/unit/test_rfb.py, drop the expectedFailure marker, rename
    it for the behaviour it checks rather than the issue number, and delete
    this file.
    """

    def setUp(self) -> None:
        self.client = rfb.RFBClient()
        self.client.transport = mock.Mock()
        self.client.factory = mock.Mock()

    @unittest.expectedFailure
    def test_empty_auth_failure_reason_ends_the_handshake_once(self) -> None:
        finish = mock.Mock()

        def stop_on_reentry(proceed: bool) -> None:
            # Unfixed, this is re-entered without end; setting the parser's
            # own stop flag breaks the loop so the test fails instead of hangs.
            if finish.call_count > 1:
                self.client._aborted = True

        finish.side_effect = stop_on_reentry
        self.client._finishSecurity = finish  # type: ignore[assignment]
        self.client.vncAuthFailed = mock.Mock()  # type: ignore[assignment]

        self.client.dataReceived(b"RFB 003.008\n")
        self.client.dataReceived(b"\x01\x01")  # one security type: None
        self.client.dataReceived(
            b"\x00\x00\x00\x01"  # SecurityResult: failed
            b"\x00\x00\x00\x00"  # reason-length 0
        )

        self.client.vncAuthFailed.assert_called_once_with(b"")
        finish.assert_called_once_with(False)
