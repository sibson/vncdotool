"""Raw wire capture for the ``vnclog --capture`` discovery kit.

Scrubbing happens *before* bytes touch disk, and is kept here, socket-free,
so it can be unit tested. Two independent redactions:

* The VNC-auth challenge and response are located by walking the handshake
  state machine, not by pattern matching -- both are high-entropy and
  indistinguishable from any other 16-byte span by content alone.
* Literal occurrences of the proxy's own password are replaced wherever
  they appear. Best-effort defence only: VNC auth never puts the password
  on the wire in the clear, and a span crossing a ``feed()`` boundary is
  missed.

Auth types with no scrubber (Diffie-Hellman/ARD, used by macOS Screen
Sharing) are named in ``unscrubbed_auth`` rather than passing their key
exchange through with an empty ``scrubbed`` list implying it was safe.
See ``docs/capture.rst``.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from struct import unpack
from typing import Any, Generator

from .const import AuthTypes

MARKER = b"\x00" * 16

Direction = str  # "s2c" or "c2s"

# What _run() is currently waiting for: (direction, nbytes, "pass"|"scrub").
_Want = tuple[Direction, int, str]


class HandshakeScrubber:
    """Tracks an RFB handshake across both directions of a proxied stream.

    :meth:`feed` takes raw bytes in arrival order and returns what should
    reach disk, with the VNC-auth challenge/response replaced by ``MARKER``.
    Once the handshake is done it passes bytes straight through.
    """

    def __init__(self) -> None:
        self.protocol_version: str | None = None
        self.negotiated_version: tuple[int, int] | None = None
        self.security_types: list[int] = []
        self.security_type: int | None = None
        self.scrubbed: list[str] = []
        self.unscrubbed_auth: str | None = None
        self.width: int | None = None
        self.height: int | None = None

        self._bufs: dict[Direction, bytearray] = {"s2c": bytearray(), "c2s": bytearray()}
        self._gen: Generator[_Want, bytes, None] | None = self._run()
        self._want: _Want | None = None
        self._advance(None)

    # -- driving the handshake state machine --------------------------------

    def _advance(self, sent: bytes | None) -> None:
        if self._gen is None:
            return
        try:
            if sent is None:
                self._want = next(self._gen)
            else:
                self._want = self._gen.send(sent)
        except StopIteration:
            self._gen = None
            self._want = None

    def feed(self, direction: Direction, data: bytes) -> bytes:
        if not data:
            return b""

        buf = self._bufs[direction]

        if self._gen is None or self._want is None or self._want[0] != direction:
            # Not tracking this direction, so nothing pending here is a
            # secret: flush it with the new data, unmodified.
            buf += data
            out = bytes(buf)
            del buf[:]
            return out

        buf += data
        out = bytearray()

        while self._gen is not None and self._want is not None and self._want[0] == direction:
            _, nbytes, mode = self._want
            if len(buf) < nbytes:
                break
            chunk = bytes(buf[:nbytes])
            del buf[:nbytes]
            out += MARKER if mode == "scrub" else chunk
            self._advance(chunk)

        # No longer tracked, so flush rather than hold these back forever.
        if buf and (self._gen is None or self._want is None or self._want[0] != direction):
            out += buf
            del buf[:]

        return bytes(out)

    def flush(self) -> dict[Direction, bytes]:
        """Bytes left buffered per direction when the connection ends.

        Bytes buffered mid-secret are dropped instead of returned: half a
        challenge is still a fragment of a secret.
        """
        out: dict[Direction, bytes] = {"s2c": b"", "c2s": b""}
        for direction in ("s2c", "c2s"):
            buf = self._bufs[direction]
            if not buf:
                continue
            pending_is_secret = (
                self._want is not None and self._want[0] == direction and self._want[2] == "scrub"
            )
            if not pending_is_secret:
                out[direction] = bytes(buf)
            del buf[:]
        return out

    # -- the handshake description -------------------------------------------

    def _run(self) -> Generator[_Want, bytes, None]:
        server_head = yield ("s2c", 12, "pass")
        self.protocol_version = server_head.decode("ascii", "replace").rstrip("\n")

        # Branch on the client's reply, not the server's greeting: per RFC
        # 6143 7.1.1 that reply governs the rest of the exchange, so a client
        # downgrading below 3.7 would otherwise take this down the wrong path
        # and miss the challenge/response entirely.
        client_head = yield ("c2s", 12, "pass")
        try:
            negotiated = (int(client_head[4:7]), int(client_head[8:11]))
        except (ValueError, IndexError):
            return
        self.negotiated_version = negotiated

        if negotiated >= (3, 7):
            num_types_b = yield ("s2c", 1, "pass")
            num_types = num_types_b[0]
            if num_types == 0:
                return  # connection-failed reason string follows; not tracked
            types_b = yield ("s2c", num_types, "pass")
            self.security_types = list(types_b)
            sectype_b = yield ("c2s", 1, "pass")
            sectype = sectype_b[0]
        else:
            auth_b = yield ("s2c", 4, "pass")
            sectype = int.from_bytes(auth_b, "big")
            if sectype == AuthTypes.INVALID:
                return
            self.security_types = [sectype]

        self.security_type = sectype

        if sectype == AuthTypes.VNC_AUTHENTICATION:
            yield ("s2c", 16, "scrub")
            self.scrubbed.append("vnc-auth-challenge")
            yield ("c2s", 16, "scrub")
            self.scrubbed.append("vnc-auth-response")
        elif sectype not in (AuthTypes.NONE, AuthTypes.INVALID):
            # Key-exchange bytes pass through unredacted, so name the type
            # rather than let an empty `scrubbed` list imply it was safe.
            looked_up = AuthTypes.lookup(sectype)
            name = getattr(looked_up, "name", None) or str(looked_up)
            self.unscrubbed_auth = f"{name.lower().replace('_', '-')}({int(sectype)})"

        # SecurityResult follows in every case but one: pre-3.8 with
        # AuthTypes.NONE jumps straight to ClientInit.
        if not (negotiated < (3, 8) and sectype == AuthTypes.NONE):
            result_b = yield ("s2c", 4, "pass")
            (result,) = unpack("!I", result_b)
            if result != 0:
                return  # auth failed/too-many-tries; reason string not tracked

        yield ("c2s", 1, "pass")  # ClientInit: shared flag

        # ServerInit: width(2) height(2) pixel-format(16) name-len(4).
        server_init = yield ("s2c", 24, "pass")
        self.width, self.height = unpack("!HH", server_init[:4])

        # Server name follows; nothing past it carries a tracked secret.
        return


def scrub_password(data: bytes, password: bytes | None) -> tuple[bytes, bool]:
    """Redact literal occurrences of `password` in `data`.

    Best-effort: only catches a password landing entirely within one chunk.
    """
    if not password or password not in data:
        return data, False
    marker = b"\x00" * len(password)
    return data.replace(password, marker), True


@dataclass
class CaptureWriter:
    """Scrubbed s2c/c2s streams and meta.json fields for one connection.

    Owns no file handles: the caller decides when to flush to disk.
    """

    server: str
    password: bytes | None = None
    scrubber: HandshakeScrubber = field(default_factory=HandshakeScrubber)
    s2c: bytearray = field(default_factory=bytearray)
    c2s: bytearray = field(default_factory=bytearray)
    _password_scrubbed: bool = False
    capture_timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def feed_s2c(self, data: bytes) -> None:
        self._feed("s2c", data)

    def feed_c2s(self, data: bytes) -> None:
        self._feed("c2s", data)

    def _feed(self, direction: Direction, data: bytes) -> None:
        scrubbed = self.scrubber.feed(direction, data)
        self._append(direction, scrubbed)

    def _append(self, direction: Direction, data: bytes) -> None:
        if not data:
            return
        scrubbed, hit = scrub_password(data, self.password)
        if hit:
            self._password_scrubbed = True
        buf = self.s2c if direction == "s2c" else self.c2s
        buf += scrubbed

    def flush(self) -> None:
        """Emit whatever the scrubber was still holding back, at disconnect."""
        pending = self.scrubber.flush()
        for direction, data in pending.items():
            self._append(direction, data)

    def scrubbed_list(self) -> list[str]:
        names = list(self.scrubber.scrubbed)
        if self._password_scrubbed:
            names.append("password")
        return names

    def meta(self, vncdotool_version: str) -> dict[str, Any]:
        return {
            "server": self.server,
            "vncdotool_version": vncdotool_version,
            "capture_timestamp": self.capture_timestamp,
            "protocol_version": self.scrubber.protocol_version,
            "security_types": self.scrubber.security_types,
            "scrubbed": self.scrubbed_list(),
            "unscrubbed_auth": self.scrubber.unscrubbed_auth,
            "geometry": (
                {"width": self.scrubber.width, "height": self.scrubber.height}
                if self.scrubber.width is not None and self.scrubber.height is not None
                else None
            ),
        }

    def write(self, directory: str) -> None:
        self.flush()
        with open(os.path.join(directory, "s2c.bin"), "wb") as fh:
            fh.write(self.s2c)
        with open(os.path.join(directory, "c2s.bin"), "wb") as fh:
            fh.write(self.c2s)


def check_capture_dir(path: str) -> None:
    """Validate `path` is usable as a --capture target.

    Creates nothing: callers create the directory only once every other
    argument has validated, so a later `op.error()` leaves nothing behind.
    """
    if os.path.exists(path):
        if not os.path.isdir(path):
            raise ValueError(f"--capture target {path!r} exists and is not a directory")
        if os.listdir(path):
            raise ValueError(f"--capture target {path!r} exists and is not empty -- refusing to mix captures")


def write_meta(path: str, meta: dict[str, Any]) -> None:
    with open(path, "w") as fh:
        json.dump(meta, fh, indent=2, sort_keys=True)
        fh.write("\n")
