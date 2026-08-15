#!/usr/bin/env python3
"""Replay a captured (or hand-scripted) RFB byte stream at a real VNC client.

A maintainer's local tool, never shipped and never a CI fixture. See
``docs/capture.rst`` for what it is for and how to drive it.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import zipfile
from typing import Any, NamedTuple, Optional, Union

from twisted.internet import reactor
from twisted.internet.protocol import Protocol, ServerFactory

from vncdotool.capture import HandshakeScrubber
from vncdotool.const import AuthTypes

log = logging.getLogger(__name__)

DEFAULT_PORT = 5999
DEFAULT_BIND = "127.0.0.1"
DEFAULT_CLIENT_TIMEOUT = 30.0

WaitMessage = tuple[str, int]
PauseMessage = tuple[str, float]
Message = Union[bytes, WaitMessage, PauseMessage]

# The two auth types vncdotool implements, and so the two it can locate the
# secret inside: a capture of either replays with that secret zeroed. Any
# other type reaching a capture at all means --capture-raw-unsafe-auth was
# passed, so its key exchange is in the archive verbatim.
SCRUBBED_AUTH_TYPES = (AuthTypes.VNC_AUTHENTICATION, AuthTypes.DIFFIE_HELLMAN)


class Capture(NamedTuple):
    """A ``vnclog --capture-raw`` archive, as far as replay cares."""

    s2c: bytes
    c2s: Optional[bytes]
    meta: Optional[dict]


def load_capture(archive_path: str) -> Capture:
    """Read ``s2c.bin`` (required), ``c2s.bin`` and ``meta.json`` (optional)
    out of a ``vnclog --capture-raw`` zip archive.
    """
    if not os.path.isfile(archive_path):
        raise ValueError(f"--capture {archive_path!r}: no such file")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
            if "s2c.bin" not in names:
                raise ValueError(
                    f"--capture {archive_path!r}: no s2c.bin inside -- expected a "
                    "`vnclog --capture-raw` archive (see docs/capture.rst)"
                )
            return Capture(
                s2c=archive.read("s2c.bin"),
                c2s=archive.read("c2s.bin") if "c2s.bin" in names else None,
                meta=json.loads(archive.read("meta.json")) if "meta.json" in names else None,
            )
    except zipfile.BadZipFile as exc:
        raise ValueError(
            f"--capture {archive_path!r}: not a zip archive ({exc}) -- expected a "
            "`vnclog --capture-raw` archive (see docs/capture.rst)"
        )


def load_script(path: str) -> list[Message]:
    """Load and validate a ``--script FILE``'s top-level ``MESSAGES`` list.

    ``exec()``d against an explicit namespace: scripts are trusted code.
    """
    with open(path, "rb") as fh:
        source = fh.read()
    namespace: dict[str, Any] = {"__name__": "__replay_script__", "__file__": path}
    exec(compile(source, path, "exec"), namespace)  # noqa: S102 -- trusted dev tool input

    messages = namespace.get("MESSAGES")
    if messages is None:
        raise ValueError(f"--script {path!r}: must define a top-level MESSAGES list")
    if not isinstance(messages, list):
        raise ValueError(f"--script {path!r}: MESSAGES must be a list, got {type(messages).__name__}")
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
        raise ValueError(
            f"--script {path!r}: MESSAGES[{i}] is {item!r}; expected bytes, "
            '("wait", nbytes: int), or ("pause", seconds: int | float)'
        )
    return messages


def recorded_security_type(s2c_data: bytes, c2s_data: bytes) -> Optional[int]:
    """Which security type the original capture session negotiated.

    Walks recorded bytes only, no live client. None if the streams run out
    before the choice is known.
    """
    scrubber = HandshakeScrubber()
    positions = {scrubber.s2c: 0, scrubber.c2s: 0}
    data = {scrubber.s2c: s2c_data, scrubber.c2s: c2s_data}
    while scrubber._want is not None:
        tap, nbytes, _scrub = scrubber._want
        start = positions[tap]
        chunk = data[tap][start : start + nbytes]
        if len(chunk) < nbytes:
            return None
        positions[tap] = start + nbytes
        tap.feed(chunk)
        if scrubber.security_type is not None:
            return scrubber.security_type
    return None


def scrub_warnings(security_type: Optional[int]) -> list[str]:
    """What this capture's auth path means for replay.

    Driven by the security type the recorded session actually negotiated --
    read back off ``c2s.bin`` -- rather than ``meta.json``, which records the
    types the server *offered* and not the one the client picked.
    """
    if security_type == AuthTypes.VNC_AUTHENTICATION:
        return [
            "this capture negotiated VNC auth, whose challenge/response are zeroed at "
            "capture time -- replaying it sends an all-zero challenge, and a real client's "
            "response to it will not match what the original server expected. Fine for "
            "pre-auth negotiation bugs; not usable past a successful VNC auth."
        ]
    if security_type == AuthTypes.DIFFIE_HELLMAN:
        return [
            "this capture negotiated ARD auth. Its Diffie-Hellman exchange is recorded in "
            "the clear and replays exactly; only the AES block carrying the username and "
            "password is zeroed."
        ]
    if security_type not in (None, AuthTypes.NONE) + SCRUBBED_AUTH_TYPES:
        return [
            f"this capture negotiated security type {security_type}, which vnclog cannot "
            "scrub -- it was recorded under --capture-raw-unsafe-auth, so replaying it "
            "replays that key exchange (and whatever credentials it carried) unmodified."
        ]
    return []


class ReplayProtocol(Protocol):  # type: ignore[misc]
    """Shared plumbing: count what the client sends, notice when it stalls."""

    def connectionMade(self) -> None:
        self.buffer = bytearray()
        self.received = 0
        self._stall_call = None

    def dataReceived(self, data: bytes) -> None:
        self.buffer += data
        self.received += len(data)
        log.debug("client -> server: %s", data.hex())
        self._cancel_stall()
        self.advance()

    def connectionLost(self, reason: Any = None) -> None:
        self._cancel_stall()
        self.factory.connection_finished()

    def advance(self) -> None:
        """Send whatever can be sent now. Called on connect and on input."""
        raise NotImplementedError

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


class CaptureReplay(ReplayProtocol):
    """Serve a recorded ``s2c.bin``, waiting for the client through the handshake.

    The handshake is a conversation -- what the client says next depends on
    what it was sent -- so the recorded bytes go out one step at a time,
    against the client's real replies. The framebuffer traffic afterwards
    needs no such care and goes out in one go.

    The steps come from HandshakeScrubber's grammar, at the cost of reaching
    into its private ``_want`` state: if that moves, this moves with it.
    Sharing the grammar is what keeps the two from drifting apart.
    """

    def connectionMade(self) -> None:
        super().connectionMade()
        self.transport.setTcpNoDelay(True)
        self.pos = 0
        self.scrubber = HandshakeScrubber()
        if not self.factory.wait_for_client:
            self._send_remainder()
            return
        self.advance()

    def advance(self) -> None:
        scrubber = self.scrubber
        while scrubber._want is not None:
            tap, nbytes, _scrub = scrubber._want
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
            if self._diverged():
                return
        self._send_remainder()

    def _diverged(self) -> bool:
        """Has the live client picked a different security type than the capture?

        Recorded bytes past the security-type choice are only valid for the
        auth path the original client took. Sending them down another path
        desyncs the client silently, so the connection ends here instead.
        """
        recorded = self.factory.recorded_security_type
        live = self.scrubber.security_type
        if recorded is None or live is None or live == recorded:
            return False
        log.error(
            "security-type divergence: the live client chose %r, but this capture's session "
            "negotiated %r. The rest of the capture assumes the original auth path and would "
            "desync the client, so this connection is being closed. Replay against a client "
            "configured the same way, e.g. with/without -p.",
            AuthTypes.lookup(live), AuthTypes.lookup(recorded),
        )
        self.transport.loseConnection()
        return True

    def _send_remainder(self) -> None:
        remainder = self.factory.capture.s2c[self.pos :]
        if remainder:
            self.transport.write(remainder)
            self.pos = len(self.factory.capture.s2c)
        self.transport.loseConnection()


class ScriptReplay(ReplayProtocol):
    """Serve a hand-written ``MESSAGES`` scenario, the forcing pattern for a
    bug no capture reproduces.
    """

    def connectionMade(self) -> None:
        super().connectionMade()
        self.transport.setTcpNoDelay(True)
        self.step = 0
        self.advance()

    def advance(self) -> None:
        messages = self.factory.messages
        while self.step < len(messages):
            message = messages[self.step]
            if isinstance(message, (bytes, bytearray)):
                self.transport.write(bytes(message))
            elif message[0] == "wait":
                if self.received < message[1]:
                    self.expect(message[1])
                    return
            else:
                self.step += 1
                reactor.callLater(message[1], self.advance)
                return
            self.step += 1
        self.transport.loseConnection()


class ReplayFactory(ServerFactory):  # type: ignore[misc]
    def __init__(
        self,
        capture: Optional[Capture] = None,
        messages: Optional[list[Message]] = None,
        wait_for_client: bool = True,
        client_timeout: Optional[float] = DEFAULT_CLIENT_TIMEOUT,
        forever: bool = False,
    ) -> None:
        self.capture = capture
        self.messages = messages
        self.wait_for_client = wait_for_client
        self.client_timeout = client_timeout
        self.forever = forever
        self.recorded_security_type: Optional[int] = None
        if capture is not None and capture.c2s is not None:
            self.recorded_security_type = recorded_security_type(capture.s2c, capture.c2s)

    def buildProtocol(self, addr: Any) -> ReplayProtocol:
        log.info("client connected from %s", addr)
        protocol = CaptureReplay() if self.capture is not None else ScriptReplay()
        protocol.factory = self
        return protocol

    def connection_finished(self) -> None:
        log.info("client disconnected")
        if not self.forever and reactor.running:
            reactor.stop()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="replay_server.py",
        description=__doc__.split("\n\n", 1)[0],
        epilog="See docs/capture.rst for what a capture contains, what replay can and cannot "
        "reproduce, and why an unscrubbed capture must not be served off localhost.",
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
        help=f"interface to listen on (default {DEFAULT_BIND}, i.e. local connections only -- "
        "an unscrubbed capture can replay credentials verbatim, so opening this up is your "
        "call to make deliberately)",
    )
    parser.add_argument(
        "--no-wait-for-client", action="store_true",
        help="--capture only: send the whole recorded stream at once instead of sending the "
        "handshake a step at a time and waiting for the client's real reply to each. Waiting "
        "is the default because a real client replies mid-handshake, and sending past its "
        "reply desyncs it; it is also what makes the security-type divergence check possible",
    )
    parser.add_argument(
        "--client-timeout", type=float, default=DEFAULT_CLIENT_TIMEOUT, metavar="SECONDS",
        help=f"warn if the client sends nothing for this long (default {DEFAULT_CLIENT_TIMEOUT})",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="hexdump client->server bytes")
    parser.add_argument(
        "--forever", action="store_true",
        help="keep accepting a new client after each connection ends, instead of exiting",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="replay_server: %(levelname)s: %(message)s",
    )

    try:
        if args.capture:
            factory = ReplayFactory(
                capture=load_capture(args.capture),
                wait_for_client=not args.no_wait_for_client,
                client_timeout=args.client_timeout,
                forever=args.forever,
            )
            for warning in scrub_warnings(factory.recorded_security_type):
                log.warning("%s", warning)
        else:
            factory = ReplayFactory(
                messages=load_script(args.script),
                client_timeout=args.client_timeout,
                forever=args.forever,
            )
    except ValueError as exc:
        parser.error(str(exc))

    reactor.listenTCP(args.listen, factory, interface=args.bind)
    log.info("listening on %s:%s", args.bind, args.listen)
    reactor.run()


if __name__ == "__main__":
    main()
