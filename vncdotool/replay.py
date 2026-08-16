"""Serving a capture back at a real VNC client; see ``docs/capture.rst``."""

from __future__ import annotations

import json
import logging
import os
import zipfile
from struct import unpack
from typing import Any, NamedTuple, Optional

from twisted.internet import reactor
from twisted.internet.protocol import Protocol, ServerFactory

from .capture import HandshakeScrubber
from .const import MsgC2S, QemuClientMessage

log = logging.getLogger(__name__)

DEFAULT_PORT = 5999
DEFAULT_BIND = "127.0.0.1"
DEFAULT_SERVER = f"{DEFAULT_BIND}::{DEFAULT_PORT}"
DEFAULT_CLIENT_TIMEOUT = 30.0

NEED_MORE = -1
UNKNOWN_MESSAGE = -2


class Capture(NamedTuple):
    """A ``vnclog --capture-raw`` archive, as far as replay cares."""

    s2c: bytes
    session_vdo: bytes
    meta: Optional[dict]

    @property
    def auth_preserved(self) -> bool:
        """Recorded with ``--capture-raw-unsafe``, so the handshake is the real one."""
        return bool(self.meta and self.meta.get("auth") == "preserved")

    @property
    def negotiated_version(self) -> Optional[tuple[int, int]]:
        """The RFB version the ORIGINAL client and server agreed on, if recorded.

        None for an archive with no meta, or an older one predating this field."""
        value = self.meta.get("negotiated_version") if self.meta else None
        return tuple(value) if value else None


def load_capture(archive_path: str) -> Capture:
    """Read ``s2c.bin`` (required), ``session.vdo`` and ``meta.json`` (optional).

    ``c2s.bin`` is evidence for a human: the live client speaks for itself."""
    if not os.path.isfile(archive_path):
        raise ValueError(f"{archive_path!r}: no such file")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
            if "s2c.bin" not in names:
                raise ValueError(
                    f"{archive_path!r}: no s2c.bin inside -- expected a "
                    "`vnclog --capture-raw` archive (see docs/capture.rst)"
                )
            return Capture(
                s2c=archive.read("s2c.bin"),
                session_vdo=archive.read("session.vdo") if "session.vdo" in names else b"",
                meta=json.loads(archive.read("meta.json")) if "meta.json" in names else None,
            )
    except zipfile.BadZipFile as exc:
        raise ValueError(
            f"{archive_path!r}: not a zip archive ({exc}) -- expected a "
            "`vnclog --capture-raw` archive (see docs/capture.rst)"
        )


def client_message_length(buffer: bytes) -> int:
    """Size of the client message at the head of `buffer`, or ``NEED_MORE`` /
    ``UNKNOWN_MESSAGE`` if it cannot be measured yet, or at all."""
    kind = buffer[0]
    if kind == MsgC2S.SET_PIXEL_FORMAT:
        return 20
    if kind == MsgC2S.SET_ENCODING:
        if len(buffer) < 4:
            return NEED_MORE
        return 4 + 4 * unpack("!H", buffer[2:4])[0]
    if kind == MsgC2S.FRAMEBUFFER_UPDATE_REQUEST:
        return 10
    if kind == MsgC2S.KEY_EVENT:
        return 8
    if kind == MsgC2S.POINTER_EVENT:
        return 6
    if kind == MsgC2S.CLIENT_CUT_TEXT:
        if len(buffer) < 8:
            return NEED_MORE
        return 8 + unpack("!I", buffer[4:8])[0]
    if kind == MsgC2S.QEMU_CLIENT_MESSAGE:
        if len(buffer) < 2:
            return NEED_MORE
        if buffer[1] == QemuClientMessage.EXTENDED_KEY_EVENT:
            return 12
        return UNKNOWN_MESSAGE
    return UNKNOWN_MESSAGE


def saw_update_request(buffer: bytearray) -> bool:
    """Take whole client messages off `buffer` until one asks for a framebuffer."""
    while buffer:
        length = client_message_length(buffer)
        if length == UNKNOWN_MESSAGE:
            log.warning(
                "client sent message type %d, which this tool cannot measure; serving the "
                "rest of the capture rather than wait for a request it cannot recognise",
                buffer[0],
            )
            del buffer[:]
            return True
        if length == NEED_MORE or len(buffer) < length:
            return False
        kind = buffer[0]
        del buffer[:length]
        if kind == MsgC2S.FRAMEBUFFER_UPDATE_REQUEST:
            return True
    return False


class ReplayProtocol(Protocol):
    """Play a recorded ``s2c.bin`` back at whatever connects, paced through
    HandshakeScrubber's public contract: ``waiting()`` plus ``s2c.feed()``/``c2s.feed()``."""

    def connectionMade(self) -> None:
        self.buffer = bytearray()
        self._stall_call = None
        self.transport.setTcpNoDelay(True)
        self.pos = 0
        self.exhausted = False
        self.awaiting_request = False
        self.served = False
        self._version_checked = False
        self.scrubber = HandshakeScrubber()
        self.advance()

    def dataReceived(self, data: bytes) -> None:
        if data:
            self.served = True
        if self.exhausted:
            return
        self.buffer += data
        log.debug("client -> server: %s", data.hex())
        self._cancel_stall()
        self.advance()

    def connectionLost(self, reason: Any = None) -> None:
        self._cancel_stall()
        self.factory.connection_finished(self.served)

    def advance(self) -> None:
        if self.exhausted:
            return
        scrubber = self.scrubber
        while (waiting := scrubber.waiting()) is not None:
            direction, nbytes = waiting
            if direction == "s2c":
                chunk = self.factory.capture.s2c[self.pos : self.pos + nbytes]
                if len(chunk) < nbytes:
                    # Truncated capture: leave the short remainder to the
                    # final send.
                    break
                self.transport.write(chunk)
                self.pos += nbytes
                scrubber.s2c.feed(chunk)
            else:
                if len(self.buffer) < nbytes:
                    self.expect(nbytes)
                    return
                chunk = bytes(self.buffer[:nbytes])
                del self.buffer[:nbytes]
                scrubber.c2s.feed(chunk)
                if self._version_mismatch():
                    return
        self._serve_session()

    def _version_mismatch(self) -> bool:
        """True, and the connection closed, if the live client just negotiated
        a version other than the one this capture's shape is fixed to."""
        if self._version_checked or self.scrubber.negotiated_version is None:
            return False
        self._version_checked = True
        archived = self.factory.capture.negotiated_version
        if archived is None or archived == self.scrubber.negotiated_version:
            return False
        log.error(
            "client negotiated RFB %d.%d, but this capture was recorded against a client "
            "that negotiated RFB %d.%d; it can only be replayed by a client negotiating the "
            "recorded version",
            *self.scrubber.negotiated_version,
            *archived,
        )
        self.transport.loseConnection()
        self.exhausted = True
        return True

    def _serve_session(self) -> None:
        """Hold the framebuffer until the client asks for one."""
        s2c = self.factory.capture.s2c
        handshake_done = self.scrubber.waiting() is None
        # `advance` already wrote everything through the server name; here
        # we only gate on the update request once the grammar has finished.
        if not self.awaiting_request and handshake_done and self.scrubber.width is not None:
            self.awaiting_request = True
        if self.awaiting_request and not saw_update_request(self.buffer):
            self.expect(10)
            return
        remainder = s2c[self.pos :]
        if remainder and handshake_done and self.scrubber.width is None:
            log.warning(
                "could not pace %s past the handshake; serving the rest of the "
                "capture unpaced, which may desync a client that hasn't caught up",
                self.scrubber.unstrippable_auth or "this capture",
            )
        if remainder:
            self.transport.write(remainder)
            self.pos = len(s2c)
        self.exhausted = True
        log.info("capture exhausted; holding the connection open until the client closes it")

    def expect(self, nbytes: int) -> None:
        """Arm the stall warning while waiting for `nbytes` from the client."""
        timeout = self.factory.client_timeout
        if timeout is None or timeout <= 0 or self._stall_call is not None:
            return
        self._stall_call = reactor.callLater(timeout, self._stalled, nbytes)

    def _cancel_stall(self) -> None:
        if self._stall_call is not None and self._stall_call.active():
            self._stall_call.cancel()
        self._stall_call = None

    def _stalled(self, nbytes: int) -> None:
        self._stall_call = None
        log.warning(
            "timed out after %ss waiting for the client to send %d bytes (got %d) -- "
            "client may have stalled",
            self.factory.client_timeout, nbytes, len(self.buffer),
        )


class ReplayFactory(ServerFactory):
    def __init__(
        self,
        capture: Capture,
        client_timeout: Optional[float] = DEFAULT_CLIENT_TIMEOUT,
        forever: bool = False,
    ) -> None:
        self.capture = capture
        self.client_timeout = client_timeout
        self.forever = forever

    def buildProtocol(self, addr: Any) -> ReplayProtocol:
        log.info("client connected from %s", addr)
        protocol = ReplayProtocol()
        protocol.factory = self
        return protocol

    def connection_finished(self, served: bool) -> None:
        log.info("client disconnected")
        # An unsent probe connection (port check: connect, then close with no
        # bytes) must not stop a one-shot server before the real client arrives.
        if served and not self.forever and reactor.running:
            reactor.stop()
