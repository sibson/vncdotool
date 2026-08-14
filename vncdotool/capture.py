"""Raw wire capture for the ``vnclog --capture`` discovery kit.

Scrubbing happens *before* bytes touch disk, and is kept here, socket-free,
so it can be unit tested. Secrets are located by walking the handshake state
machine, never by pattern matching -- every one of them is high-entropy and
indistinguishable from any other span of the same length by content alone:

* VNC auth (:attr:`AuthTypes.VNC_AUTHENTICATION`): the 16-byte challenge and
  the 16-byte response.
* ARD / Apple Screen Sharing (:attr:`AuthTypes.DIFFIE_HELLMAN`): the
  128-byte AES-ECB block carrying username and password. The surrounding
  Diffie-Hellman values (generator, modulus, both public keys) are public by
  construction and pass through, so the capture still shows the key exchange
  a compatibility bug would live in.

Redacted spans are replaced by an equal number of zero bytes, never by a
shorter or longer marker: a capture whose byte offsets shifted under
scrubbing would no longer replay.

An auth type with no scrubber aborts the capture and names itself, unless
the contributor passes ``--capture-unsafe-auth``. Writing an unscrubbed key
exchange to a file destined for a public issue tracker is a decision for a
human with a disposable password, not a default. See ``docs/capture.rst``.

Scrubbing stops at the end of the handshake. Everything the session itself
carries -- keystrokes, clipboard -- is recorded verbatim; that risk is
documented rather than filtered, because a capture with its input stream
rewritten is no longer evidence of what the server did.
"""

from __future__ import annotations

import json
import os
import time
import zipfile
from dataclasses import dataclass, field
from struct import unpack
from typing import Any, Generator

from .const import AuthTypes, Encoding

MARKER = b"\x00" * 16

# AES-ECB over a fixed 64-byte username + 64-byte password struct; see
# RFBClient._encryptArd().
ARD_CREDENTIALS_LEN = 128

Direction = str  # "s2c" or "c2s"

# What _run() is currently waiting for: (direction, nbytes, "pass"|"scrub").
_Want = tuple[Direction, int, str]


class HandshakeScrubber:
    """Tracks an RFB handshake across both directions of a proxied stream.

    :meth:`feed` takes raw bytes in arrival order and returns what should
    reach disk, with the VNC-auth challenge/response replaced by ``MARKER``.
    Once the handshake is done it passes bytes straight through.
    """

    def __init__(self, allow_unsafe_auth: bool = False) -> None:
        self.allow_unsafe_auth = allow_unsafe_auth
        self.protocol_version: str | None = None
        self.negotiated_version: tuple[int, int] | None = None
        self.security_types: list[int] = []
        self.security_type: int | None = None
        self.scrubbed: list[str] = []
        self.unscrubbed_auth: str | None = None
        # Set when an auth type we cannot scrub is selected and the
        # contributor has not opted in; the caller drops the capture.
        self.abort_reason: str | None = None
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
            # Equal-length redaction: byte offsets after a scrubbed span
            # have to match the live stream or the capture stops replaying.
            out += bytes(nbytes) if mode == "scrub" else chunk
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
        elif sectype == AuthTypes.DIFFIE_HELLMAN:
            # ARD / Apple Screen Sharing, laid out as RFBClient._handleDHAuth
            # reads it: generator(2) keyLen(2), modulus(keyLen),
            # serverKey(keyLen), then the client's reply. Only the client's
            # AES block is secret -- the DH values are public by design, and
            # keeping them is what makes the capture useful for the ARD
            # compatibility bugs this kit exists to chase.
            head = yield ("s2c", 4, "pass")
            _generator, key_len = unpack("!HH", head)
            yield ("s2c", key_len, "pass")  # modulus
            yield ("s2c", key_len, "pass")  # server public key
            yield ("c2s", ARD_CREDENTIALS_LEN, "scrub")
            self.scrubbed.append("ard-credentials")
            yield ("c2s", key_len, "pass")  # client public key
        elif sectype not in (AuthTypes.NONE, AuthTypes.INVALID):
            # No scrubber for this type: its key exchange would reach disk
            # whole. Name it, and stop unless a human opted in.
            looked_up = AuthTypes.lookup(sectype)
            name = getattr(looked_up, "name", None) or str(looked_up)
            self.unscrubbed_auth = f"{name.lower().replace('_', '-')}({int(sectype)})"
            if not self.allow_unsafe_auth:
                self.abort_reason = (
                    f"the session negotiated {self.unscrubbed_auth}, which vncdotool cannot scrub; "
                    "the capture would contain the credential exchange verbatim. "
                    "Re-run with --capture-unsafe-auth, using a disposable password you "
                    "rotate afterwards, if you need this exchange captured."
                )
                return

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
    # encoding number -> rectangles seen. Recorded from the decoded stream,
    # never from the client's SetEncodings request: a server may answer in
    # any encoding it likes, and which one it actually chose is the whole
    # question a capture from an unhostable server is meant to answer.
    encodings_seen: dict[int, int] = field(default_factory=dict)
    _password_scrubbed: bool = False
    capture_timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    @property
    def abort_reason(self) -> str | None:
        return self.scrubber.abort_reason

    def note_encoding(self, encoding: int) -> None:
        self.encodings_seen[encoding] = self.encodings_seen.get(encoding, 0) + 1

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

    def encodings_list(self) -> list[dict[str, Any]]:
        """`encodings_seen` as JSON, ordered and named where we know the name."""
        out = []
        for encoding in sorted(self.encodings_seen):
            looked_up = Encoding.lookup(encoding)
            name = getattr(looked_up, "name", None)
            out.append(
                {
                    "encoding": encoding,
                    "name": name.lower().replace("_", "-") if name else None,
                    "rectangles": self.encodings_seen[encoding],
                }
            )
        return out

    def meta(self, vncdotool_version: str) -> dict[str, Any]:
        return {
            "server": self.server,
            "vncdotool_version": vncdotool_version,
            "capture_timestamp": self.capture_timestamp,
            "protocol_version": self.scrubber.protocol_version,
            "security_types": self.scrubber.security_types,
            "scrubbed": self.scrubbed_list(),
            "unscrubbed_auth": self.scrubber.unscrubbed_auth,
            "encodings_seen": self.encodings_list(),
            "geometry": (
                {"width": self.scrubber.width, "height": self.scrubber.height}
                if self.scrubber.width is not None and self.scrubber.height is not None
                else None
            ),
        }

    def write_archive(self, path: str, meta: dict[str, Any], session_vdo: bytes = b"") -> None:
        """Write the whole capture as one zip, ready to attach to an issue.

        Built at a temporary path and renamed into place, so an interrupted
        write cannot leave a half archive looking like a complete capture.
        """
        self.flush()
        partial = path + ".part"
        try:
            with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("s2c.bin", bytes(self.s2c))
                archive.writestr("c2s.bin", bytes(self.c2s))
                archive.writestr("session.vdo", session_vdo)
                archive.writestr("meta.json", json.dumps(meta, indent=2, sort_keys=True) + "\n")
            os.replace(partial, path)
        except BaseException:
            if os.path.exists(partial):
                os.unlink(partial)
            raise


def check_capture_target(path: str) -> None:
    """Validate `path` is usable as a --capture target.

    Creates nothing: the archive is written when the session ends, so a
    later `op.error()` leaves nothing behind.
    """
    if not path.endswith(".zip"):
        raise ValueError(f"--capture target {path!r} must end in .zip -- captures are written as one archive")
    if os.path.exists(path):
        raise ValueError(f"--capture target {path!r} already exists -- refusing to overwrite a capture")
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        raise ValueError(f"--capture target directory {parent!r} does not exist")
