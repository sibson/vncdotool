"""Fence against a real TigerVNC, the server that motivated #322/#323.

The socket-level test is what makes the client-level ones meaningful:
TigerVNC sends a ServerFence only to a client that offered
``PSEUDO_FENCE``, so vncdotool's own decision to offer it is what puts
message 248 on the wire. Before the fence handler existed that byte
reached ``_handleConnection``'s unknown-message branch and ended the
session, which is why offering the encoding and answering the message
have to land together.
"""

import socket
import struct
import threading
from unittest import TestCase

from PIL import Image

from vncdotool.const import Encoding, FenceFlags, MsgC2S, MsgS2C

from .utils import (
    HOST,
    TIGERVNC,
    distinct_colours,
    has_expected_content,
    port_open,
    run_vncdo,
    screenshot_dir,
)

HANDSHAKE_TIMEOUT = 10.0


class _Peer:
    """The least RFB needed to reach the first server message after SetEncodings.

    Deliberately not vncdotool's own client: the point is to control which
    encodings are offered, and to read the raw message id the server replies
    with rather than whatever the client under test makes of it.
    """

    def __init__(self, encodings):
        self.sock = socket.create_connection((HOST, TIGERVNC.port), HANDSHAKE_TIMEOUT)
        self.sock.settimeout(HANDSHAKE_TIMEOUT)
        self.buffer = b""
        self._handshake(encodings)

    def close(self):
        self.sock.close()

    def recv(self, n):
        while len(self.buffer) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise AssertionError(f"server closed with {len(self.buffer)} of {n} bytes read")
            self.buffer += chunk
        out, self.buffer = self.buffer[:n], self.buffer[n:]
        return out

    def _handshake(self, encodings):
        self.recv(12)
        self.sock.sendall(b"RFB 003.008\n")
        (count,) = struct.unpack("!B", self.recv(1))
        types = self.recv(count)
        assert 1 in types, f"tigervnc offered no None security type: {list(types)}"
        self.sock.sendall(b"\x01")
        (result,) = struct.unpack("!I", self.recv(4))
        assert result == 0, f"None security type rejected: {result}"
        self.sock.sendall(b"\x01")  # shared
        self.width, self.height = struct.unpack("!HH", self.recv(4))
        self.recv(16)  # pixel format
        (length,) = struct.unpack("!I", self.recv(4))
        self.recv(length)  # desktop name
        body = struct.pack("!BxH", 2, len(encodings))
        self.sock.sendall(body + b"".join(struct.pack("!i", e) for e in encodings))

    def request_update(self):
        self.sock.sendall(
            struct.pack("!BBHHHH", 3, 0, 0, 0, self.width, self.height)
        )

    def first_message_id(self):
        (msgid,) = struct.unpack("!B", self.recv(1))
        return msgid

    def send_fence(self, flags, payload=b"\xaa"):
        self.sock.sendall(
            struct.pack("!BxxxIB", MsgC2S.CLIENT_FENCE, flags, len(payload)) + payload
        )


BASE_ENCODINGS = [
    Encoding.RAW,
    Encoding.PSEUDO_DESKTOP_SIZE,
    Encoding.PSEUDO_LAST_RECT,
]


class TestFenceOnTheWire(TestCase):

    def setUp(self) -> None:
        if not port_open(HOST, TIGERVNC.port):
            self.fail(
                f"{TIGERVNC.name} not reachable on {HOST}:{TIGERVNC.port} -- {TIGERVNC.how_to_start}"
            )

    def test_offering_fence_makes_tigervnc_send_one(self) -> None:
        peer = _Peer([*BASE_ENCODINGS, Encoding.PSEUDO_FENCE])
        self.addCleanup(peer.close)
        peer.request_update()

        self.assertEqual(
            peer.first_message_id(), MsgS2C.SERVER_FENCE,
            "tigervnc did not lead with a ServerFence for a client offering PSEUDO_FENCE",
        )

    def test_not_offering_fence_keeps_tigervnc_quiet(self) -> None:
        """The counterpart: a client that stays silent about the encoding is
        never sent a fence, so the handler is only load-bearing because
        VNCDoToolFactory.fence defaults to True.
        """
        peer = _Peer(BASE_ENCODINGS)
        self.addCleanup(peer.close)
        peer.request_update()

        self.assertNotEqual(
            peer.first_message_id(), MsgS2C.SERVER_FENCE,
            "tigervnc sent a ServerFence to a client that never offered PSEUDO_FENCE",
        )


class TestFenceThroughTheClient(TestCase):

    def setUp(self) -> None:
        if not port_open(HOST, TIGERVNC.port):
            self.fail(
                f"{TIGERVNC.name} not reachable on {HOST}:{TIGERVNC.port} -- {TIGERVNC.how_to_start}"
            )

    def _assert_captures(self, path) -> None:
        result = run_vncdo(TIGERVNC, "capture", str(path))
        self.assertEqual(
            result.returncode, 0,
            f"vncdo exited {result.returncode} against a server that fences, stderr:\n{result.stderr}",
        )
        with Image.open(path) as image:
            self.assertEqual(image.size, TIGERVNC.size)
            colours = distinct_colours(image)
        self.assertTrue(
            has_expected_content(TIGERVNC, colours),
            "capture is a single flat colour, no screen content was decoded",
        )

    def test_capture_survives_the_fences_it_asks_for(self) -> None:
        self._assert_captures(screenshot_dir() / f"{TIGERVNC.name}-fence.png")

    def test_capture_survives_another_client_fencing(self) -> None:
        """#322's shape: a second client on an -AlwaysShared session, with the
        first one fencing hard throughout. A fence is addressed to one
        connection, so the noise this makes must not reach or stall the
        capture; that it does not is the reason a fence the other client sent
        cannot be what #322 saw arrive.
        """
        other = _Peer([*BASE_ENCODINGS, Encoding.PSEUDO_FENCE])
        self.addCleanup(other.close)
        other.request_update()

        stop = threading.Event()

        def fence_until_stopped():
            other.sock.settimeout(0.3)
            while not stop.is_set():
                try:
                    other.send_fence(FenceFlags.REQUEST | FenceFlags.BLOCK_BEFORE)
                    other.send_fence(FenceFlags.REQUEST | FenceFlags.SYNC_NEXT)
                except OSError:
                    return
                stop.wait(0.1)

        noise = threading.Thread(target=fence_until_stopped, daemon=True)
        noise.start()
        self.addCleanup(noise.join, 5.0)
        self.addCleanup(stop.set)

        self._assert_captures(screenshot_dir() / f"{TIGERVNC.name}-fence-shared.png")
