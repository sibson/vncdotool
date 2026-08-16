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
from .const import MsgC2S

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


def server_init_end(s2c_data: bytes, offset: int) -> Optional[int]:
    """Where ServerInit ends: 24 fixed bytes plus the server's name, or None
    if the capture is too short to hold it."""
    if len(s2c_data) < offset + 24:
        return None
    (name_len,) = unpack("!I", s2c_data[offset + 20 : offset + 24])
    end = offset + 24 + name_len
    return end if len(s2c_data) >= end else None


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
    """Play a recorded ``s2c.bin`` back at whatever connects, paced off
    HandshakeScrubber's private ``_want`` so the two cannot drift apart."""

    def connectionMade(self) -> None:
        self.buffer = bytearray()
        self._stall_call = None
        self.transport.setTcpNoDelay(True)
        self.pos = 0
        self.exhausted = False
        self.awaiting_request = False
        self.scrubber = HandshakeScrubber()
        self.advance()

    def dataReceived(self, data: bytes) -> None:
        self.buffer += data
        log.debug("client -> server: %s", data.hex())
        self._cancel_stall()
        self.advance()

    def connectionLost(self, reason: Any = None) -> None:
        self._cancel_stall()
        self.factory.connection_finished()

    def advance(self) -> None:
        if self.exhausted:
            return
        scrubber = self.scrubber
        while scrubber._want is not None:
            tap, nbytes = scrubber._want
            if tap is scrubber.s2c:
                chunk = self.factory.capture.s2c[self.pos : self.pos + nbytes]
                if len(chunk) < nbytes:
                    # Truncated capture: leave the short remainder to the
                    # final send.
                    break
                self.transport.write(chunk)
                self.pos += nbytes
                tap.feed(chunk)
            else:
                if len(self.buffer) < nbytes:
                    self.expect(nbytes)
                    return
                chunk = bytes(self.buffer[:nbytes])
                del self.buffer[:nbytes]
                tap.feed(chunk)
        self._serve_session()

    def _serve_session(self) -> None:
        """Send ServerInit, then hold the framebuffer until it is asked for.

        One finite recording, so those bytes get one chance to be useful."""
        s2c = self.factory.capture.s2c
        # `scrubber.width` is set by parsing ServerInit, so its 24 fixed
        # bytes are behind `pos` and only the server name is still to come.
        if not self.awaiting_request and self.scrubber.width is not None:
            end = server_init_end(s2c, self.pos - 24)
            if end is not None:
                self.transport.write(s2c[self.pos : end])
                self.pos = end
                self.awaiting_request = True
        if self.awaiting_request and not saw_update_request(self.buffer):
            self.expect(10)
            return
        remainder = s2c[self.pos :]
        if remainder:
            self.transport.write(remainder)
            self.pos = len(s2c)
        self.exhausted = True
        log.info("capture exhausted; holding the connection open until the client closes it")

    def expect(self, nbytes: int) -> None:
        """Arm the stall warning while waiting for `nbytes` from the client."""
        timeout = self.factory.client_timeout
        if timeout is None or self._stall_call is not None:
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

    def connection_finished(self) -> None:
        log.info("client disconnected")
        if not self.forever and reactor.running:
            reactor.stop()
