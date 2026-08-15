#!/usr/bin/env python3
"""Replay a captured (or hand-scripted) RFB byte stream at a real VNC client.

A maintainer's local tool, never shipped and never a CI fixture: a
contributed capture exists to help a human narrow down a bug, and the end
product is always a unit test with the relevant bytes inlined. (The tool's
own handshake logic is tested, from hand-built bytes, like any other code.)

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

Waiting for the client (``--capture`` only)
-------------------------------------------

The handshake is a conversation: the client replies partway through, and
what it says next depends on what it was sent. Sending the recorded
stream in one go therefore desyncs a real client. By default this tool
sends the handshake a step at a time and waits for the client's real
reply to each, then sends the remainder in one go -- the framebuffer
traffic after the handshake needs no such care. ``--no-wait-for-client``
sends everything at once, for when the waiting is itself what you are
debugging.

The steps come from ``vncdotool.capture.HandshakeScrubber``'s handshake
grammar (imported lazily, so ``--no-wait-for-client`` and ``--script``
run without ``vncdotool`` importable). Sharing the grammar keeps the two
from drifting apart, at the cost of reaching into its private
``_gen``/``_want`` state -- if those move,
:func:`replay_handshake_step_by_step` needs a matching update.

Security-type divergence
------------------------

Recorded bytes past the security-type choice are only valid for the auth
path the original client picked, and sending them down another path
desyncs the live client silently. So while waiting for the client, this
also walks ``c2s.bin`` to learn what the original session negotiated, and
closes the connection with a warning if the live client chooses
differently. Without ``c2s.bin`` the divergence cannot be detected.

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
from typing import Any, Callable, NamedTuple, Optional, Tuple, Union

DEFAULT_PORT = 5999
DEFAULT_BIND = "127.0.0.1"
DEFAULT_CLIENT_TIMEOUT = 30.0
RECV_CHUNK = 4096

WaitMessage = Tuple[str, int]
PauseMessage = Tuple[str, float]
Message = Union[bytes, WaitMessage, PauseMessage]


class Capture(NamedTuple):
    """A ``vnclog --capture-raw`` archive, as far as replay cares.

    Only ``s2c`` is ever sent: ``c2s`` drives the security-type divergence
    check and ``meta`` the startup banner.
    """

    s2c: bytes
    c2s: Optional[bytes]
    meta: Optional[dict]


def load_capture(archive_path: str) -> Capture:
    """Read ``s2c.bin`` (required), ``c2s.bin`` and ``meta.json`` (optional)
    out of a ``vnclog --capture-raw`` zip archive.
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
    return Capture(s2c_data, c2s_data, meta)


# Spelled out rather than imported from vncdotool.const, so this stays
# runnable with no vncdotool on the path (see the module docstring).
AUTH_NONE = 1
AUTH_VNC = 2
AUTH_ARD = 30

# The two auth types vncdotool implements, and so the two it can locate the
# secret inside: a capture of either replays with that secret zeroed. Any
# other type reaching a capture at all means --capture-raw-unsafe-auth was
# passed, so its key exchange is in the archive verbatim.
SCRUBBED_AUTH_TYPES = (AUTH_VNC, AUTH_ARD)


def scrub_warnings(recorded_security_type: Optional[int]) -> list[str]:
    """Warnings about what this capture's auth path means for replay.

    Driven by the security type the recorded session actually negotiated --
    read back off ``c2s.bin`` -- rather than ``meta.json``, which records the
    types the server *offered* and not the one the client picked.
    """
    warnings = []
    if recorded_security_type == AUTH_VNC:
        warnings.append(
            "this capture negotiated VNC auth, whose challenge/response are zeroed at "
            "capture time -- replaying it sends an all-zero challenge, and a real "
            "client's response to it will not match what the original server actually "
            "expected. Fine for pre-auth negotiation bugs; not usable to reproduce "
            "anything past a successful VNC auth. See the module docstring."
        )
    elif recorded_security_type == AUTH_ARD:
        warnings.append(
            "this capture negotiated ARD auth. Its Diffie-Hellman exchange is recorded "
            "in the clear and replays exactly; only the AES block carrying the username "
            "and password is zeroed."
        )
    elif recorded_security_type not in (None, AUTH_NONE) + SCRUBBED_AUTH_TYPES:
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


@dataclass
class HandshakeResult:
    """Outcome of one `replay_handshake_step_by_step()` call."""

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


def replay_handshake_step_by_step(
    s2c_data: bytes,
    send: Callable[[bytes], None],
    recv_exact: Callable[[int], bytes],
    recorded_c2s_data: Optional[bytes] = None,
) -> HandshakeResult:
    """Send the handshake part of `s2c_data` one step at a time, waiting via
    `recv_exact` for the live client's real reply to each.

    `HandshakeResult.offset` is how far into `s2c_data` the handshake
    consumed; the caller sends the rest from there. If `recorded_c2s_data`
    is given, a live client choosing a different security type sets
    `diverged`, and the caller must send nothing past `offset`.

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
                # Truncated capture: leave the short remainder to the caller.
                break
            send(chunk)
            pos += len(chunk)
            tap.feed(chunk)
        else:
            data = recv_exact(nbytes)
            if len(data) < nbytes:
                # Client never sent this step; nothing left to wait for.
                break
            tap.feed(data)

        if (
            recorded_security_type is not None
            and scrubber.security_type is not None
            and scrubber.security_type != recorded_security_type
        ):
            return HandshakeResult(
                offset=pos,
                diverged=True,
                recorded_security_type=recorded_security_type,
                live_security_type=scrubber.security_type,
            )

    return HandshakeResult(offset=pos)


class ClientReader:
    """Background thread draining one client socket, tracking both a total
    received count (for script ``("wait", n)``) and a queue consumable N
    bytes at a time (for the handshake's `recv_exact`).
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

    def _await(self, have: Callable[[], int], want: int, timeout: Optional[float], units: str) -> None:
        """Wait for `have()` to reach `want`, or for the client to go away.

        Caller holds `self._cond`. A timeout is not an error here: it is
        reported and the caller decides, since every caller can say
        something more useful about the shortfall than this can. `timeout`
        of None waits forever, which is why the default is not None.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        while have() < want and not self._stopped:
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                print(
                    f"replay_server: WARNING: timed out after {timeout}s waiting for the client "
                    f"to send {want} {units} (got {have()}) -- client may have stalled",
                    file=sys.stderr,
                )
                return
            self._cond.wait(remaining)

    def wait_for_total(self, nbytes: int, timeout: Optional[float] = None) -> bool:
        """Block until the client has sent >= `nbytes` cumulative bytes."""
        with self._cond:
            self._await(lambda: self.total_received, nbytes, timeout, "cumulative bytes")
            return self.total_received >= nbytes

    def read_exact(self, nbytes: int, timeout: Optional[float] = None) -> bytes:
        """Consume and return `nbytes` from the client, or fewer if the
        connection ends or `timeout` expires first.
        """
        with self._cond:
            self._await(lambda: len(self._buf), nbytes, timeout, "bytes")
            got = min(nbytes, len(self._buf))
            out = bytes(self._buf[:got])
            del self._buf[:got]
            return out


DIVERGENCE_WARNING = """\
replay_server: WARNING: security-type divergence -- the live client chose security type \
{live!r}, but the capture's original session negotiated {recorded!r}. The rest of this \
capture's bytes assume the original auth path and would desync the client if sent, so this \
connection is being closed instead of sending them. See the module docstring's \
'Security-type divergence' section -- re-capture (or replay) against a client configured the \
same way, e.g. with/without -p."""


def handle_capture_connection(
    conn: socket.socket,
    s2c_data: bytes,
    wait_for_client: bool,
    verbose: bool,
    recorded_c2s_data: Optional[bytes] = None,
    client_timeout: Optional[float] = None,
) -> None:
    reader = ClientReader(conn, verbose=verbose)
    reader.start()
    offset = 0
    if wait_for_client:
        result = replay_handshake_step_by_step(
            s2c_data,
            conn.sendall,
            lambda nbytes: reader.read_exact(nbytes, timeout=client_timeout),
            recorded_c2s_data=recorded_c2s_data,
        )
        if result.diverged:
            print(
                DIVERGENCE_WARNING.format(
                    live=result.live_security_type, recorded=result.recorded_security_type
                ),
                file=sys.stderr,
            )
            return
        offset = result.offset
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
does exercise this tool's own handshake logic with hand-built inline bytes.
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
        "--no-wait-for-client", action="store_true",
        help="--capture only: send the whole recorded stream at once instead of sending the "
        "handshake a step at a time and waiting for the client's real reply to each. Waiting "
        "is the default because a real client replies mid-handshake, and sending past its "
        "reply desyncs it; it is also what makes the security-type divergence check possible. "
        "Use this when the waiting itself is what you are debugging",
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

    capture: Optional[Capture] = None
    messages: Optional[list[Message]] = None
    if args.capture:
        capture = load_capture(args.capture)
        recorded_type = (
            _recorded_security_type(capture.s2c, capture.c2s) if capture.c2s is not None else None
        )
        for warning in scrub_warnings(recorded_type):
            print(f"replay_server: WARNING: {warning}", file=sys.stderr)
        description = f"--capture {args.capture}"
        if args.no_wait_for_client:
            description += " (not waiting for the client)"
    else:
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
                if capture is not None:
                    handle_capture_connection(
                        conn, capture.s2c, not args.no_wait_for_client, args.verbose,
                        recorded_c2s_data=capture.c2s,
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
