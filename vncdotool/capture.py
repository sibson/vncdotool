"""Raw wire capture for the ``vnclog --capture-raw`` discovery kit.

Records a synthetic ``none``-auth handshake; see ``docs/capture.rst``."""

from __future__ import annotations

import json
import os
import time
import zipfile
from dataclasses import dataclass, field
from struct import pack, unpack
from typing import Any, Generator, NamedTuple

from .const import AuthTypes, Encoding

# AES-ECB over a fixed 64-byte username + 64-byte password struct; see
# RFBClient._encryptArd().
ARD_CREDENTIALS_LEN = 128


class Tap:
    """One direction of the proxied connection.

    Callers hold the tap for the direction they are feeding, so no direction
    argument travels through the code: ``scrubber.s2c.feed(data)`` returns
    what that direction should record.
    """

    def __init__(self, scrubber: HandshakeScrubber, name: str) -> None:
        self.name = name  # "s2c" / "c2s", for messages only
        self.pending = bytearray()
        self._scrubber = scrubber

    def __repr__(self) -> str:
        return f"<Tap {self.name}>"

    def feed(self, data: bytes) -> bytes:
        return self._scrubber._feed(self, data)

    def flush(self) -> bytes:
        return self._scrubber._flush(self)


class _Want(NamedTuple):
    """What the handshake is waiting for next."""

    tap: Tap
    nbytes: int


class HandshakeScrubber:
    """Tracks an RFB handshake across both directions of a proxied stream.

    Feed :attr:`s2c` / :attr:`c2s`; each returns what that side records."""

    def __init__(self, preserve_auth: bool = False) -> None:
        self.s2c = Tap(self, "s2c")
        self.c2s = Tap(self, "c2s")
        self.preserve_auth = preserve_auth
        self.protocol_version: str | None = None
        self.negotiated_version: tuple[int, int] | None = None
        self.security_types: list[int] = []
        self.security_type: int | None = None
        self.unstrippable_auth: str | None = None
        # Set when an auth type we cannot follow is selected without an
        # opt-in; the caller drops the capture.
        self.abort_reason: str | None = None
        self.width: int | None = None
        self.height: int | None = None

        self._gen: Generator[_Want, bytes, None] | None = self._run()
        self._want: _Want | None = None
        # What to record for the chunk just read, decided by the handshake
        # after seeing it: None records the bytes themselves.
        self._recording: bytes | None = None
        # True across the auth exchange, so a half-arrived credential is
        # dropped at disconnect rather than flushed.
        self._in_auth = False
        self._advance(None)

    def _record(self, data: bytes) -> None:
        self._recording = data

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

    def _give_up(self, why: str) -> None:
        """Stop the capture when we can no longer follow the handshake.

        Not knowing where the credentials end means not being able to strip them."""
        if self.preserve_auth:
            return
        self.abort_reason = (
            f"{why}; vncdotool can no longer tell where this handshake's credentials end, "
            "so it cannot strip them. Re-run with --capture-raw-unsafe, using a disposable "
            "password you rotate afterwards, if you need this session captured."
        )

    def _waiting_on(self, tap: Tap) -> _Want | None:
        """What the handshake wants from `tap`, if it is watching it at all."""
        if self._gen is None or self._want is None or self._want.tap is not tap:
            return None
        return self._want

    def _feed(self, tap: Tap, data: bytes) -> bytes:
        if not data:
            return b""

        buf = tap.pending

        if self._waiting_on(tap) is None:
            # Not watching this direction, so nothing pending here is a
            # secret: flush it with the new data, unmodified.
            buf += data
            out = bytes(buf)
            del buf[:]
            return out

        buf += data
        out = bytearray()

        while (want := self._waiting_on(tap)) is not None:
            if len(buf) < want.nbytes:
                break
            chunk = bytes(buf[:want.nbytes])
            del buf[:want.nbytes]
            # Fail closed inside the auth exchange: a step that forgets to
            # call _record must drop the chunk, not leak it.
            fail_closed_default = b"" if self._in_auth and not self.preserve_auth else chunk
            self._recording = None
            self._advance(chunk)
            if self.preserve_auth:
                out += chunk
            else:
                out += fail_closed_default if self._recording is None else self._recording

        # No longer watched, so flush rather than hold these back forever.
        if buf and self._waiting_on(tap) is None:
            out += buf
            del buf[:]

        return bytes(out)

    def _flush(self, tap: Tap) -> bytes:
        """Bytes left buffered on `tap`; dropped while a partial handshake is still being rewritten."""
        mid_rewrite = self._gen is not None and not self.preserve_auth
        out = b"" if mid_rewrite and tap.pending else bytes(tap.pending)
        del tap.pending[:]
        return out

    # -- the handshake description -------------------------------------------

    def _run(self) -> Generator[_Want, bytes, None]:
        server_head = yield _Want(self.s2c, 12)
        self.protocol_version = server_head.decode("ascii", "replace").rstrip("\n")

        # Branch on the client's reply, not the server's greeting: per RFC
        # 6143 7.1.1 that reply governs the rest of the exchange, so a client
        # downgrading below 3.7 would otherwise take this down the wrong path
        # and miss the challenge/response entirely.
        client_head = yield _Want(self.c2s, 12)
        try:
            negotiated = (int(client_head[4:7]), int(client_head[8:11]))
        except (ValueError, IndexError):
            # Fail closed. Giving up here would put both directions into
            # passthrough, so a server that carried on regardless would have
            # its challenge and response recorded in the clear.
            self._give_up(f"could not parse the client's version reply {bytes(client_head)!r}")
            return
        self.negotiated_version = negotiated

        if negotiated >= (3, 7):
            num_types_b = yield _Want(self.s2c, 1)
            num_types = num_types_b[0]
            if num_types == 0:
                # Connection refused; the reason string follows and is not
                # tracked. Nothing was negotiated, so nothing is rewritten.
                return
            # The real count and list are re-emitted as one `none` offer by
            # the step below, so this byte records nothing of its own.
            self._record(b"")
            types_b = yield _Want(self.s2c, num_types)
            self.security_types = list(types_b)
            self._record(bytes([1, AuthTypes.NONE]))
            sectype_b = yield _Want(self.c2s, 1)
            self._record(bytes([AuthTypes.NONE]))
            sectype = sectype_b[0]
        else:
            auth_b = yield _Want(self.s2c, 4)
            sectype = int.from_bytes(auth_b, "big")
            if sectype == AuthTypes.INVALID:
                return
            self._record(pack("!I", AuthTypes.NONE))
            self.security_types = [sectype]

        self.security_type = sectype
        self._in_auth = True

        if sectype == AuthTypes.VNC_AUTHENTICATION:
            yield _Want(self.s2c, 16)  # challenge
            yield _Want(self.c2s, 16)  # response
        elif sectype == AuthTypes.DIFFIE_HELLMAN:
            # ARD, laid out as RFBClient._handleDHAuth reads it. A `none`
            # handshake has nowhere for the DH values, so they go too.
            head = yield _Want(self.s2c, 4)
            _generator, key_len = unpack("!HH", head)
            yield _Want(self.s2c, key_len)  # modulus
            yield _Want(self.s2c, key_len)  # server public key
            yield _Want(self.c2s, ARD_CREDENTIALS_LEN)  # username + password
            yield _Want(self.c2s, key_len)  # client public key
        elif sectype not in (AuthTypes.NONE, AuthTypes.INVALID):
            # No grammar for this type, so its exchange has no known end.
            looked_up = AuthTypes.lookup(sectype)
            name = getattr(looked_up, "name", None) or str(looked_up)
            self.unstrippable_auth = f"{name.lower().replace('_', '-')}({int(sectype)})"
            if not self.preserve_auth:
                self.abort_reason = (
                    f"the session negotiated {self.unstrippable_auth}, whose exchange vncdotool "
                    "cannot follow; it cannot tell where the credentials end, so it cannot strip "
                    "them. Re-run with --capture-raw-unsafe, using a disposable password "
                    "you rotate afterwards, if you need this exchange captured."
                )
            # Either way this is the end of what can be followed: both
            # directions pass through from here, recorded as they arrive.
            return

        self._in_auth = False

        # SecurityResult follows in every case but one: pre-3.8 with
        # AuthTypes.NONE jumps straight to ClientInit.
        if not (negotiated < (3, 8) and sectype == AuthTypes.NONE):
            result_b = yield _Want(self.s2c, 4)
            (result,) = unpack("!I", result_b)
            if result != 0:
                # Pre-3.8 `none` has no SecurityResult slot to put a real
                # failure in; recording it there would desync the replay.
                if negotiated < (3, 8):
                    self._record(b"")
                return  # auth failed/too-many-tries; reason string not tracked
            # `none` carries a SecurityResult only from 3.8 on.
            self._record(pack("!I", 0) if negotiated >= (3, 8) else b"")

        yield _Want(self.c2s, 1)  # ClientInit: shared flag

        # ServerInit: width(2) height(2) pixel-format(16) name-len(4).
        server_init = yield _Want(self.s2c, 24)
        self.width, self.height = unpack("!HH", server_init[:4])

        # Server name follows; nothing past it carries a tracked secret.
        return


@dataclass
class CaptureWriter:
    """Scrubbed s2c/c2s streams and meta.json fields for one connection.

    Owns no file handles: the caller decides when to flush to disk.
    """

    server: str
    scrubber: HandshakeScrubber = field(default_factory=HandshakeScrubber)
    s2c: bytearray = field(default_factory=bytearray)
    c2s: bytearray = field(default_factory=bytearray)
    # encoding number -> rectangles seen, from the decoded stream rather than
    # the client's SetEncodings request: a server may answer in any encoding
    # it likes, and which one it chose is what the capture is asked for.
    encodings_seen: dict[int, int] = field(default_factory=dict)
    capture_timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    @property
    def abort_reason(self) -> str | None:
        return self.scrubber.abort_reason

    def note_encoding(self, encoding: int) -> None:
        self.encodings_seen[encoding] = self.encodings_seen.get(encoding, 0) + 1

    def feed_s2c(self, data: bytes) -> None:
        self.s2c += self.scrubber.s2c.feed(data)

    def feed_c2s(self, data: bytes) -> None:
        self.c2s += self.scrubber.c2s.feed(data)

    def flush(self) -> None:
        """Emit whatever the scrubber was still holding back, at disconnect."""
        self.s2c += self.scrubber.s2c.flush()
        self.c2s += self.scrubber.c2s.flush()

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
            "negotiated_version": (
                list(self.scrubber.negotiated_version) if self.scrubber.negotiated_version is not None else None
            ),
            # Evidence about the server, not a description of s2c.bin, which
            # by default records a `none` handshake instead.
            "security_types": self.scrubber.security_types,
            "security_type": self.scrubber.security_type,
            "auth": "preserved" if self.scrubber.preserve_auth else "stripped",
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
    """Validate `path` is usable as a --capture-raw target.

    Creates nothing: the archive is written when the session ends, so a
    later `op.error()` leaves nothing behind.
    """
    if not path.endswith(".zip"):
        raise ValueError(f"--capture-raw target {path!r} must end in .zip -- captures are written as one archive")
    if os.path.exists(path):
        raise ValueError(
            f"--capture-raw target {path!r} already exists -- "
            "refusing to overwrite a capture; pick another filename"
        )
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        raise ValueError(f"--capture-raw target directory {parent!r} does not exist")
