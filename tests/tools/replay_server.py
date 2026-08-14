#!/usr/bin/env python3
"""Replay a captured (or hand-scripted) RFB byte stream at a real VNC client.

A maintainer's local tool, never shipped and never a CI fixture: a
contributed capture exists to help a human narrow down a bug, and the end
product is always a unit test with the relevant bytes inlined. (The tool's
own pacing logic is tested, from hand-built bytes, like any other code.)

Run it with the stdlib interpreter, no install needed::

    python tests/tools/replay_server.py --capture ./issue-123-capture.zip --verbose
    python tests/tools/replay_server.py --script ./repro.py

then point a real client at it::

    vncdo -s 127.0.0.1::5999 key enter type "hello" capture screen.png

``--capture ARCHIVE.zip`` replays the ``s2c.bin`` inside a ``vnclog
--capture-raw`` archive; ``c2s.bin`` drives the divergence check below and
``session.vdo``/``meta.json`` are for a human to read. ``--script FILE``
runs a hand-written scenario
instead: a Python file defining a ``MESSAGES`` list of ``bytes`` to send,
``("wait", nbytes)`` to block until the client has sent that much, or
``("pause", seconds)``. It is run through ``exec()`` -- **scripts are
trusted developer code**, like a local config file. Either way, the
connection is closed once there is nothing left to send.

Pacing (``--capture`` only)
---------------------------

The handshake is interactive -- the client replies mid-stream -- so
firehosing ``s2c.bin`` desyncs a real client. ``--pace handshake`` (the
default) sends the handshake a step at a time, blocking for each real
reply, then firehoses the rest; framebuffer traffic is not paced to the
client's request cadence. ``--pace none`` firehoses everything, for when
the pacing logic itself is in the way.

Pacing walks the handshake grammar of
``vncdotool.capture.HandshakeScrubber`` (imported lazily, so ``--pace
none`` and ``--script`` run without ``vncdotool`` importable). That keeps
the two from drifting apart, at the cost of reaching into its private
``_gen``/``_want`` state -- if those move, :func:`replay_handshake_paced`
needs a matching update.

Security-type divergence
------------------------

Recorded bytes past the security-type choice are only valid for the auth
path the original client picked, and sending them down another path
desyncs the live client silently. So ``--pace handshake`` also walks
``c2s.bin`` to learn what the original session negotiated, and closes the
connection with a warning if the live client chooses differently. Without
``c2s.bin`` the divergence cannot be detected.

Scrubbed captures cannot replay through VNC auth
------------------------------------------------

A capture of a VNC-authenticated server has its challenge and response
zeroed, so a real client's DES response can never match: replay is
faithful only for ``AuthTypes.NONE`` sessions and for bugs in the pre-auth
negotiation, which is never scrubbed. The tool warns at startup when the
recorded ``c2s.bin`` shows VNC auth was the type actually negotiated --
``meta.json`` records only the types the server offered, which does not say
which one the client picked. Diffie-Hellman/ARD captures are the
opposite case -- the key exchange is present in the clear and replays
exactly; see ``docs/capture.rst`` for what that capture contains.

Because an unscrubbed capture can replay credentials verbatim, this binds
to ``127.0.0.1``. Pass ``--bind`` only for a capture you know carries
nothing sensitive.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import zipfile
from dataclasses import dataclass
from typing import Any, Callable, Optional

DEFAULT_PORT = 5999
DEFAULT_BIND = "127.0.0.1"
DEFAULT_CLIENT_TIMEOUT = 30.0
RECV_CHUNK = 4096

Message = Any  # bytes, or ("wait", int), or ("pause", float)


# --------------------------------------------------------------------------
# Loading capture directories / scripts (no sockets, so unit-testable)
# --------------------------------------------------------------------------


def load_capture(archive_path: str) -> tuple[bytes, Optional[bytes], Optional[dict]]:
    """Read ``s2c.bin`` (required), ``c2s.bin`` and ``meta.json`` (optional)
    out of a ``vnclog --capture-raw`` zip archive.

    Only ``s2c.bin`` is ever sent: ``meta.json`` feeds the startup banner and
    ``c2s.bin`` the security-type divergence check.
    """
    if not os.path.isfile(archive_path):
        raise SystemExit(f"--capture {archive_path!r}: no such file")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
            if "s2c.bin" not in names:
                raise SystemExit(
                    f"--capture {archive_path!r}: no s2c.bin inside -- expected a "
                    "`vnclog --capture-raw` archive (see docs/capture.rst)"
                )
            s2c_data = archive.read("s2c.bin")
            c2s_data = archive.read("c2s.bin") if "c2s.bin" in names else None
            meta = json.loads(archive.read("meta.json")) if "meta.json" in names else None
    except zipfile.BadZipFile as exc:
        raise SystemExit(
            f"--capture {archive_path!r}: not a zip archive ({exc}) -- expected a "
            "`vnclog --capture-raw` archive (see docs/capture.rst)"
        )
    return s2c_data, c2s_data, meta


# The two auth types vncdotool implements, and so the two it can locate the
# secret inside: a capture of either replays with that secret zeroed. Any
# other type reaching a capture at all means --capture-raw-unsafe-auth was
# passed, so its key exchange is in the archive verbatim.
SCRUBBED_AUTH_TYPES = (2, 30)  # AuthTypes.VNC_AUTHENTICATION, AuthTypes.DIFFIE_HELLMAN


def scrub_warnings(recorded_security_type: Optional[int]) -> list[str]:
    """Warnings about what this capture's auth path means for replay.

    Driven by the security type the recorded session actually negotiated --
    read back off ``c2s.bin`` -- rather than ``meta.json``, which records the
    types the server *offered* and not the one the client picked.
    """
    warnings = []
    if recorded_security_type == 2:  # AuthTypes.VNC_AUTHENTICATION
        warnings.append(
            "this capture negotiated VNC auth, whose challenge/response are zeroed at "
            "capture time -- replaying it sends an all-zero challenge, and a real "
            "client's response to it will not match what the original server actually "
            "expected. Fine for pre-auth negotiation bugs; not usable to reproduce "
            "anything past a successful VNC auth. See the module docstring."
        )
    elif recorded_security_type == 30:  # AuthTypes.DIFFIE_HELLMAN (ARD)
        warnings.append(
            "this capture negotiated ARD auth. Its Diffie-Hellman exchange is recorded "
            "in the clear and replays exactly; only the AES block carrying the username "
            "and password is zeroed."
        )
    elif recorded_security_type is not None and recorded_security_type not in (1,) + SCRUBBED_AUTH_TYPES:
        warnings.append(
            f"this capture negotiated security type {recorded_security_type}, which vnclog "
            "cannot scrub -- it was recorded under --capture-raw-unsafe-auth, so replaying "
            "it replays that key exchange (and whatever credentials it carried) unmodified."
        )
    return warnings


def load_script(path: str) -> list[Message]:
    """Load and validate a ``--script FILE``'s top-level ``MESSAGES`` list.

    ``exec()``d against an explicit namespace: scripts are trusted code.
    """
    with open(path, "rb") as fh:
        source = fh.read()
    namespace: dict[str, Any] = {"__name__": "__replay_script__", "__file__": path}
    exec(compile(source, path, "exec"), namespace)  # noqa: S102 -- trusted dev tool input, see docstring

    messages = namespace.get("MESSAGES")
    if messages is None:
        raise SystemExit(f"--script {path!r}: must define a top-level MESSAGES list")
    if not isinstance(messages, list):
        raise SystemExit(f"--script {path!r}: MESSAGES must be a list, got {type(messages).__name__}")
    for i, item in enumerate(messages):
        if isinstance(item, (bytes, bytearray)):
            continue
        if isinstance(item, tuple) and len(item) == 2:
            kind, value = item
            # bool is a subclass of int; accepting it here does no harm
            # (True/False are valid byte-counts/second-counts).
            if kind == "wait" and isinstance(value, int):
                continue
            if kind == "pause" and isinstance(value, (int, float)):
                continue
        raise SystemExit(
            f"--script {path!r}: MESSAGES[{i}] is {item!r}; expected bytes, "
            '("wait", nbytes: int), or ("pause", seconds: int | float)'
        )
    return messages


# --------------------------------------------------------------------------
# Handshake pacing (logic over caller-supplied send/recv callables)
# --------------------------------------------------------------------------


@dataclass
class PaceResult:
    """Outcome of one `replay_handshake_paced()` call."""

    offset: int  # how far into s2c_data the handshake phase consumed
    diverged: bool = False
    recorded_security_type: Optional[int] = None
    live_security_type: Optional[int] = None


def _recorded_security_type(s2c_data: bytes, c2s_data: bytes) -> Optional[int]:
    """Which security type the original capture session negotiated.

    Walks recorded bytes only, no live client. None if the streams run out
    before the choice is known.
    """
    from vncdotool.capture import HandshakeScrubber  # lazy: see module docstring

    scrubber = HandshakeScrubber()
    s2c_pos = c2s_pos = 0
    while scrubber._gen is not None and scrubber._want is not None:
        tap, nbytes, _scrub = scrubber._want
        if tap is scrubber.s2c:
            chunk = s2c_data[s2c_pos : s2c_pos + nbytes]
            if len(chunk) < nbytes:
                return None
            s2c_pos += len(chunk)
        else:
            chunk = c2s_data[c2s_pos : c2s_pos + nbytes]
            if len(chunk) < nbytes:
                return None
            c2s_pos += len(chunk)
        tap.feed(chunk)
        if scrubber.security_type is not None:
            return scrubber.security_type
    return None


def replay_handshake_paced(
    s2c_data: bytes,
    send: Callable[[bytes], None],
    recv_exact: Callable[[int], bytes],
    recorded_c2s_data: Optional[bytes] = None,
) -> PaceResult:
    """Send the handshake-phase prefix of `s2c_data`, paced against the live
    client's real replies via `recv_exact`.

    `PaceResult.offset` is how far into `s2c_data` the handshake consumed;
    the caller firehoses from there. If `recorded_c2s_data` is given, a live
    client choosing a different security type sets `diverged`, and the
    caller must send nothing past `offset`.

    `send`/`recv_exact` are injected rather than a socket so this is
    testable with plain bytes.
    """
    from vncdotool.capture import HandshakeScrubber  # lazy: see module docstring

    recorded_security_type = (
        _recorded_security_type(s2c_data, recorded_c2s_data) if recorded_c2s_data is not None else None
    )

    scrubber = HandshakeScrubber()
    pos = 0
    while scrubber._gen is not None and scrubber._want is not None:
        tap, nbytes, _scrub = scrubber._want
        if tap is scrubber.s2c:
            chunk = s2c_data[pos : pos + nbytes]
            if len(chunk) < nbytes:
                # Truncated capture: stop pacing and leave the short
                # remainder to the caller's firehose.
                break
            send(chunk)
            pos += len(chunk)
            tap.feed(chunk)
        else:
            data = recv_exact(nbytes)
            if len(data) < nbytes:
                # Client never sent this step; nothing left to pace against.
                break
            tap.feed(data)

        if (
            recorded_security_type is not None
            and scrubber.security_type is not None
            and scrubber.security_type != recorded_security_type
        ):
            return PaceResult(
                offset=pos,
                diverged=True,
                recorded_security_type=recorded_security_type,
                live_security_type=scrubber.security_type,
            )

    return PaceResult(offset=pos)


# --------------------------------------------------------------------------
# Live connection handling (sockets and threads)
# --------------------------------------------------------------------------


class ClientReader:
    """Background thread draining one client socket, tracking both a total
    received count (for script ``("wait", n)``) and a queue consumable N
    bytes at a time (for pacing's `recv_exact`).
    """

    def __init__(self, sock: socket.socket, verbose: bool = False) -> None:
        self._sock = sock
        self._verbose = verbose
        self._cond = threading.Condition()
        self._buf = bytearray()
        self.total_received = 0
        self._stopped = False
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        try:
            while True:
                try:
                    data = self._sock.recv(RECV_CHUNK)
                except OSError:
                    break
                if not data:
                    break
                if self._verbose:
                    print(f"replay_server: client -> server: {data.hex()}", file=sys.stderr)
                with self._cond:
                    self._buf += data
                    self.total_received += len(data)
                    self._cond.notify_all()
        finally:
            with self._cond:
                self._stopped = True
                self._cond.notify_all()

    def wait_for_total(self, nbytes: int, timeout: Optional[float] = None) -> bool:
        """Block until the client has sent >= `nbytes` cumulative bytes.

        `timeout` (seconds, None = wait forever) guards against a stalled
        client wedging the tool silently -- on expiry this prints a
        diagnostic to stderr before returning False.
        """
        with self._cond:
            deadline = None if timeout is None else time.monotonic() + timeout
            while self.total_received < nbytes and not self._stopped:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    print(
                        f"replay_server: WARNING: timed out after {timeout}s waiting for the "
                        f"client to send {nbytes} cumulative bytes (got {self.total_received}) "
                        "-- client may have stalled",
                        file=sys.stderr,
                    )
                    break
                self._cond.wait(remaining)
            return self.total_received >= nbytes

    def read_exact(self, nbytes: int, timeout: Optional[float] = None) -> bytes:
        """Consume and return exactly `nbytes` from the client (or fewer,
        if the connection ends, or `timeout` (seconds, None = wait
        forever) expires first -- either way a diagnostic is printed to
        stderr so a stalled client doesn't wedge the tool silently).
        """
        with self._cond:
            deadline = None if timeout is None else time.monotonic() + timeout
            while len(self._buf) < nbytes and not self._stopped:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    print(
                        f"replay_server: WARNING: timed out after {timeout}s waiting for the "
                        f"client to send {nbytes} bytes (got {len(self._buf)}) -- client may "
                        "have stalled",
                        file=sys.stderr,
                    )
                    break
                self._cond.wait(remaining)
            got = min(nbytes, len(self._buf))
            out = bytes(self._buf[:got])
            del self._buf[:got]
            return out


def handle_capture_connection(
    conn: socket.socket,
    s2c_data: bytes,
    pace: str,
    verbose: bool,
    recorded_c2s_data: Optional[bytes] = None,
    client_timeout: Optional[float] = None,
) -> None:
    reader = ClientReader(conn, verbose=verbose)
    reader.start()
    if pace == "handshake":
        result = replay_handshake_paced(
            s2c_data,
            conn.sendall,
            lambda nbytes: reader.read_exact(nbytes, timeout=client_timeout),
            recorded_c2s_data=recorded_c2s_data,
        )
        if result.diverged:
            print(
                "replay_server: WARNING: security-type divergence -- the live client chose "
                f"security type {result.live_security_type!r}, but the capture's original "
                f"session negotiated {result.recorded_security_type!r}. The rest of this "
                "capture's bytes assume the original auth path and would desync the client if "
                "sent, so this connection is being closed instead of firehosing them. See the "
                "module docstring's 'Security-type divergence' section -- re-capture (or "
                "replay) against a client configured the same way, e.g. with/without -p.",
                file=sys.stderr,
            )
            return
        offset = result.offset
    elif pace == "none":
        offset = 0
    else:
        raise ValueError(f"unknown --pace {pace!r}")
    remainder = s2c_data[offset:]
    if remainder:
        conn.sendall(remainder)


def handle_script_connection(
    conn: socket.socket,
    messages: list[Message],
    verbose: bool,
    client_timeout: Optional[float] = None,
) -> None:
    reader = ClientReader(conn, verbose=verbose)
    reader.start()
    for msg in messages:
        if isinstance(msg, (bytes, bytearray)):
            conn.sendall(bytes(msg))
        elif msg[0] == "wait":
            reader.wait_for_total(msg[1], timeout=client_timeout)
        elif msg[0] == "pause":
            time.sleep(msg[1])


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

EPILOG = """\
Scrubbed captures cannot be faithfully replayed through VNC auth: a
capture's VNC-auth challenge/response are zeroed at capture time
(docs/capture.rst), so a real client's response to the replayed all-zero
challenge will not match what the original server expected. Fine for
auth-None captures and for pre-auth negotiation bugs; not usable to
reproduce anything past a successful VNC auth. See the module docstring
for the full explanation and a worked example.

This tool is never shipped and is never a CI fixture -- no recorded
capture is ever replayed in CI, though tests/functional/test_replay.py
does exercise this tool's own pacing logic with hand-built inline bytes.
See docs/testing-framework-design.md, "3. Capture kit" -> "Replay tool".
"""


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="replay_server.py",
        description=__doc__.split("\n\n", 1)[0],
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--capture", metavar="ARCHIVE.zip",
        help="replay the s2c.bin inside a vnclog --capture-raw archive",
    )
    mode.add_argument("--script", metavar="FILE", help="run the MESSAGES scenario defined in FILE")

    parser.add_argument(
        "--listen", type=int, default=DEFAULT_PORT, metavar="PORT",
        help=f"TCP port to listen on (default {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--bind", default=DEFAULT_BIND, metavar="ADDR",
        help=f"interface to listen on (default {DEFAULT_BIND}, i.e. local connections only -- an "
        "unscrubbed capture can replay credentials verbatim, see the module docstring, so opening "
        "this up (e.g. --bind 0.0.0.0) is your call to make deliberately)",
    )
    parser.add_argument(
        "--pace", choices=("none", "handshake"), default="handshake",
        help="--capture only: 'handshake' (default) paces the handshake against the client's "
        "real replies before firehosing the rest, and checks for security-type divergence "
        "against the capture's c2s.bin if present; 'none' firehoses everything immediately "
        "with no divergence check",
    )
    parser.add_argument(
        "--client-timeout", type=float, default=DEFAULT_CLIENT_TIMEOUT, metavar="SECONDS",
        help=f"give up waiting for the client after this many seconds and print a diagnostic "
        f"(default {DEFAULT_CLIENT_TIMEOUT})",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="hexdump client->server bytes")
    lifecycle = parser.add_mutually_exclusive_group()
    lifecycle.add_argument(
        "--once", action="store_true",
        help="exit after replaying to the first client (default). This tool closes the "
        "connection itself once it has nothing left to send; it does not wait for the client "
        "to disconnect first.",
    )
    lifecycle.add_argument(
        "--forever", action="store_true",
        help="keep accepting a new client after each connection ends, instead of exiting",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    args = build_arg_parser().parse_args(argv)

    recorded_c2s_data: Optional[bytes] = None
    if args.capture:
        s2c_data, recorded_c2s_data, _meta = load_capture(args.capture)
        recorded_type = (
            _recorded_security_type(s2c_data, recorded_c2s_data) if recorded_c2s_data is not None else None
        )
        for warning in scrub_warnings(recorded_type):
            print(f"replay_server: WARNING: {warning}", file=sys.stderr)
        messages = None
        description = f"--capture {args.capture} (--pace {args.pace})"
    else:
        s2c_data = None
        messages = load_script(args.script)
        description = f"--script {args.script}"

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((args.bind, args.listen))
    server_sock.listen(1)
    print(f"replay_server: listening on {args.bind}:{args.listen} ({description})", file=sys.stderr)
    print("replay_server: accepting connections", file=sys.stderr)

    try:
        while True:
            conn, addr = server_sock.accept()
            print(f"replay_server: client connected from {addr}", file=sys.stderr)
            try:
                if s2c_data is not None:
                    handle_capture_connection(
                        conn, s2c_data, args.pace, args.verbose,
                        recorded_c2s_data=recorded_c2s_data,
                        client_timeout=args.client_timeout,
                    )
                else:
                    handle_script_connection(conn, messages, args.verbose, client_timeout=args.client_timeout)
            except (OSError, BrokenPipeError) as exc:
                print(f"replay_server: connection error: {exc}", file=sys.stderr)
            finally:
                conn.close()
            print("replay_server: client disconnected", file=sys.stderr)
            if not args.forever:
                break
    finally:
        server_sock.close()


if __name__ == "__main__":
    main()
