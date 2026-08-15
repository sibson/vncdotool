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
import shutil
import sys
import tempfile
import zipfile
from struct import pack, unpack
from typing import Any, NamedTuple, Optional, Union

from twisted.internet import reactor
from twisted.internet.protocol import Protocol, ProcessProtocol, ServerFactory

from vncdotool.capture import HandshakeScrubber
from vncdotool.const import AuthTypes, MsgC2S

log = logging.getLogger(__name__)

DEFAULT_PORT = 5999
DEFAULT_BIND = "127.0.0.1"
DEFAULT_CLIENT_TIMEOUT = 30.0
DEFAULT_SCREENSHOT = "replay.png"

WaitMessage = tuple[str, int]
PauseMessage = tuple[str, float]
Message = Union[bytes, WaitMessage, PauseMessage]

# The two vncdotool can locate the secret inside. Any other type in a
# capture means --capture-raw-unsafe-auth was passed, so its key exchange
# is in the archive verbatim.
SCRUBBED_AUTH_TYPES = (AuthTypes.VNC_AUTHENTICATION, AuthTypes.DIFFIE_HELLMAN)

VERSION_33 = (3, 3)
VERSION_37 = (3, 7)
VERSION_38 = (3, 8)

NEED_MORE = -1
UNKNOWN_MESSAGE = -2


class Capture(NamedTuple):
    """A ``vnclog --capture-raw`` archive, as far as replay cares."""

    s2c: bytes
    c2s: Optional[bytes]
    session_vdo: bytes
    meta: Optional[dict]


class Handshake(NamedTuple):
    """Where the recorded handshake ends and what it negotiated.

    ``server_init_offset`` is the ``s2c.bin`` offset of ServerInit, i.e. the
    first byte that is true of the session rather than of its auth. None
    when the recorded streams run out before that point.
    """

    security_type: Optional[int]
    server_init_offset: Optional[int]


def load_capture(archive_path: str) -> Capture:
    """Read ``s2c.bin`` (required), ``c2s.bin``, ``session.vdo`` and
    ``meta.json`` (optional) out of a ``vnclog --capture-raw`` zip archive.
    """
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
                c2s=archive.read("c2s.bin") if "c2s.bin" in names else None,
                session_vdo=archive.read("session.vdo") if "session.vdo" in names else b"",
                meta=json.loads(archive.read("meta.json")) if "meta.json" in names else None,
            )
    except zipfile.BadZipFile as exc:
        raise ValueError(
            f"{archive_path!r}: not a zip archive ({exc}) -- expected a "
            "`vnclog --capture-raw` archive (see docs/capture.rst)"
        )


def load_script(path: str) -> list[Message]:
    """Load and validate a scenario file's top-level ``MESSAGES`` list.

    ``exec()``d against an explicit namespace: scripts are trusted code.
    """
    with open(path, "rb") as fh:
        source = fh.read()
    namespace: dict[str, Any] = {"__name__": "__replay_script__", "__file__": path}
    exec(compile(source, path, "exec"), namespace)  # noqa: S102 -- trusted dev tool input

    messages = namespace.get("MESSAGES")
    if messages is None:
        raise ValueError(f"{path!r}: must define a top-level MESSAGES list")
    if not isinstance(messages, list):
        raise ValueError(f"{path!r}: MESSAGES must be a list, got {type(messages).__name__}")
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
            f"{path!r}: MESSAGES[{i}] is {item!r}; expected bytes, "
            '("wait", nbytes: int), or ("pause", seconds: int | float)'
        )
    return messages


def read_handshake(s2c_data: bytes, c2s_data: bytes) -> Handshake:
    """Walk the recorded handshake, with no live client involved.

    Reuses ``HandshakeScrubber``'s grammar -- and its private ``_want``
    state -- so the two cannot drift apart about where a handshake ends.
    """
    scrubber = HandshakeScrubber()
    positions = {scrubber.s2c: 0, scrubber.c2s: 0}
    data = {scrubber.s2c: s2c_data, scrubber.c2s: c2s_data}
    while scrubber._want is not None:
        tap, nbytes, _scrub = scrubber._want
        # The one-byte c2s read taken after the security type is known is
        # ClientInit, so the s2c stream is at ServerInit: the handshake is
        # behind us.
        if tap is scrubber.c2s and nbytes == 1 and scrubber.security_type is not None:
            return Handshake(scrubber.security_type, positions[scrubber.s2c])
        chunk = data[tap][positions[tap] : positions[tap] + nbytes]
        if len(chunk) < nbytes:
            break
        positions[tap] += nbytes
        tap.feed(chunk)
    return Handshake(scrubber.security_type, None)


def server_init_end(s2c_data: bytes, offset: int) -> Optional[int]:
    """Where ServerInit ends: 24 fixed bytes plus the server's name.

    None if the capture is too short to hold the whole thing.
    """
    if len(s2c_data) < offset + 24:
        return None
    (name_len,) = unpack("!I", s2c_data[offset + 20 : offset + 24])
    end = offset + 24 + name_len
    return end if len(s2c_data) >= end else None


def client_message_length(buffer: bytes) -> int:
    """Size of the client message at the head of `buffer`.

    ``NEED_MORE`` while its own length field is still incomplete,
    ``UNKNOWN_MESSAGE`` for a type we cannot measure and so cannot step past.
    """
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
    """Take whole client messages off `buffer` until one asks for a framebuffer.

    A capture holds a finite recording, so the framebuffer bytes get exactly
    one chance to be useful: sending them before the client has asked means
    a client that asks a moment later waits for an update that already went
    past it.
    """
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


def negotiated_version(client_reply: bytes) -> tuple[int, int]:
    """The version in a client's 12-byte reply, which governs the rest.

    Unparseable replies fall back to 3.3, the shape with the fewest
    server-side assumptions.
    """
    try:
        return (int(client_reply[4:7]), int(client_reply[8:11]))
    except (ValueError, IndexError):
        log.warning("could not parse the client's version reply %r; assuming RFB 3.3", client_reply)
        return VERSION_33


def scrub_warnings(security_type: Optional[int]) -> list[str]:
    """What this capture's auth path means for a verbatim (``--replay-auth``) replay.

    Not from ``meta.json``: that records the types the server offered, not
    the one the client picked.
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

    def spent(self) -> None:
        """Nothing recorded is left to send.

        The connection stays open: the original server hung up because its
        client did, and closing here instead would cut short whatever the
        live client is still doing with the bytes it has.
        """
        log.info("capture exhausted; holding the connection open until the client closes it")

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


class NoAuthReplay(ReplayProtocol):
    """Serve the recorded session behind a synthesised ``none`` handshake.

    Only the recorded greeting survives from the capture's own handshake:
    the security types are replaced by ``none`` alone and the auth exchange
    is skipped, so the replay needs no password and cannot desync over a
    security type the live client picked differently. What the capture is
    kept for -- the session past ServerInit -- goes out byte for byte.
    """

    def connectionMade(self) -> None:
        super().connectionMade()
        self.transport.setTcpNoDelay(True)
        self.version = VERSION_33
        self.state = "version"
        self.transport.write(self.factory.capture.s2c[:12])
        self.advance()

    def advance(self) -> None:
        while True:
            if self.state == "version":
                if len(self.buffer) < 12:
                    self.expect(12)
                    return
                self.version = negotiated_version(bytes(self.buffer[:12]))
                del self.buffer[:12]
                if self.version >= VERSION_37:
                    self.transport.write(bytes([1, AuthTypes.NONE]))
                    self.state = "security-type"
                else:
                    self.transport.write(pack("!I", AuthTypes.NONE))
                    self.state = "client-init"
            elif self.state == "security-type":
                if len(self.buffer) < 1:
                    self.expect(1)
                    return
                chosen = self.buffer[0]
                del self.buffer[:1]
                if chosen != AuthTypes.NONE:
                    log.warning(
                        "client chose security type %r, but only none was offered; "
                        "carrying on as none", AuthTypes.lookup(chosen),
                    )
                if self.version >= VERSION_38:
                    self.transport.write(pack("!I", 0))  # SecurityResult: OK
                self.state = "client-init"
            elif self.state == "client-init":
                if len(self.buffer) < 1:
                    self.expect(1)
                    return
                del self.buffer[:1]  # shared flag
                self.state = "server-init"
            elif self.state == "server-init":
                s2c = self.factory.capture.s2c
                offset = self.factory.handshake.server_init_offset
                end = server_init_end(s2c, offset)
                if end is None:  # truncated capture: send what there is
                    self.transport.write(s2c[offset:])
                    self.state = "spent"
                    self.spent()
                    return
                self.transport.write(s2c[offset:end])
                self.framebuffer_at = end
                self.state = "update-request"
            elif self.state == "update-request":
                if not saw_update_request(self.buffer):
                    self.expect(10)
                    return
                self.transport.write(self.factory.capture.s2c[self.framebuffer_at :])
                self.state = "spent"
                self.spent()
                return
            else:
                return


class CaptureReplay(ReplayProtocol):
    """Serve the recorded handshake verbatim, for a bug that lives in it.

    The steps come from HandshakeScrubber's grammar, at the cost of reaching
    into its private ``_want`` state: if that moves, this moves with it.
    Sharing the grammar is what keeps the two from drifting apart.
    """

    def connectionMade(self) -> None:
        super().connectionMade()
        self.transport.setTcpNoDelay(True)
        self.pos = 0
        self.exhausted = False
        self.awaiting_request = False
        self.scrubber = HandshakeScrubber()
        self.advance()

    def advance(self) -> None:
        if self.exhausted:
            return
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

        Recorded bytes past the choice only fit the path the original client
        took; sending them down another desyncs it silently.
        """
        recorded = self.factory.handshake.security_type
        live = self.scrubber.security_type
        if recorded is None or live is None or live == recorded:
            return False
        log.error(
            "security-type divergence: the live client chose %r, but this capture's session "
            "negotiated %r. The rest of the capture assumes the original auth path and would "
            "desync the client, so this connection is being closed. Replay against a client "
            "configured the same way, e.g. with/without -p, or drop --replay-auth.",
            AuthTypes.lookup(live), AuthTypes.lookup(recorded),
        )
        self.transport.loseConnection()
        return True

    def _send_remainder(self) -> None:
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
        self.spent()


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
        replay_auth: bool = False,
        client_timeout: Optional[float] = DEFAULT_CLIENT_TIMEOUT,
        forever: bool = False,
    ) -> None:
        self.capture = capture
        self.messages = messages
        self.client_timeout = client_timeout
        self.forever = forever
        # False once a forked vncdo owns the reactor's lifetime: the process
        # outliving its connection is how its exit status gets reported.
        self.stop_on_disconnect = True
        self.handshake = Handshake(None, None)
        if capture is not None and capture.c2s is not None:
            self.handshake = read_handshake(capture.s2c, capture.c2s)
        # Substituting none-auth means skipping to ServerInit, which we only
        # know the offset of by having read the recorded handshake through.
        self.replay_auth = replay_auth or self.handshake.server_init_offset is None

    def buildProtocol(self, addr: Any) -> ReplayProtocol:
        log.info("client connected from %s", addr)
        if self.capture is None:
            protocol: ReplayProtocol = ScriptReplay()
        elif self.replay_auth:
            protocol = CaptureReplay()
        else:
            protocol = NoAuthReplay()
        protocol.factory = self
        return protocol

    def connection_finished(self) -> None:
        log.info("client disconnected")
        if self.stop_on_disconnect and not self.forever and reactor.running:
            reactor.stop()


class ClientProcess(ProcessProtocol):  # type: ignore[misc]
    """The forked ``vncdo``, driving the capture's own recorded session.

    Replaying the archive's ``session.vdo`` rather than letting a human type
    a command line is what makes the replay faithful: the client sends the
    events the original one sent, in the order it sent them.
    """

    def __init__(self) -> None:
        self.exit_code: Optional[int] = None

    def outReceived(self, data: bytes) -> None:
        for line in data.decode("utf-8", "replace").splitlines():
            log.info("vncdo: %s", line)

    errReceived = outReceived

    def processEnded(self, reason: Any) -> None:
        self.exit_code = getattr(reason.value, "exitCode", 0) or 0
        log.info("vncdo exited %s", self.exit_code)
        if reactor.running:
            reactor.stop()


def client_script(session_vdo: bytes, screenshot: str) -> str:
    """The recorded session, plus a screenshot so a replay leaves evidence."""
    recorded = session_vdo.decode("utf-8", "replace").strip()
    return f"{recorded}\ncapture {screenshot}\n" if recorded else f"capture {screenshot}\n"


def find_vncdo() -> Optional[str]:
    """The `vncdo` belonging to the interpreter running this, else PATH's.

    Preferring our own environment's console script means a replay exercises
    the checkout being debugged rather than whatever `vncdo` a shim or a
    global install happens to resolve to.
    """
    alongside = os.path.join(os.path.dirname(sys.executable), "vncdo")
    if os.path.isfile(alongside) and os.access(alongside, os.X_OK):
        return alongside
    return shutil.which("vncdo")


def spawn_client(script: str, workdir: str, server: str) -> ClientProcess:
    """Run `vncdo` against the replay, from `workdir`, on the archive's script."""
    vncdo = find_vncdo()
    if vncdo is None:
        raise ValueError(
            "`vncdo` is not on PATH -- install vncdotool (`pip install -e .`) so its "
            "console script is available, or pass --no-client and drive a client yourself"
        )
    script_path = os.path.join(workdir, "session.vdo")
    with open(script_path, "w") as fh:
        fh.write(script)

    process = ClientProcess()
    argv = [vncdo, "-s", server, script_path]
    log.info("running %s (in %s)", " ".join(argv), workdir)
    reactor.spawnProcess(process, vncdo, argv, env=os.environ, path=workdir)
    return process


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="replay_capture.py",
        description=__doc__.split("\n\n", 1)[0],
        epilog="See docs/capture.rst for what a capture contains, what replay can and cannot "
        "reproduce, and why an unscrubbed capture must not be served off localhost.",
    )
    parser.add_argument(
        "target", metavar="ARCHIVE.zip",
        help="a vnclog --capture-raw archive to replay; a file that is not a zip is read as a "
        "MESSAGES scenario script instead (which implies --no-client)",
    )
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
        "--no-client", action="store_true",
        help="listen and stop there, instead of running the archive's session.vdo through "
        "vncdo, so a GUI viewer or a hand-written vncdo line can connect instead",
    )
    parser.add_argument(
        "--workdir", metavar="DIR",
        help="where the forked vncdo runs, and so where its screenshot lands "
        "(default: a fresh temporary directory, reported on startup)",
    )
    parser.add_argument(
        "--screenshot", default=DEFAULT_SCREENSHOT, metavar="PATH",
        help=f"screenshot the replayed session ends on (default {DEFAULT_SCREENSHOT}, relative "
        "to --workdir)",
    )
    parser.add_argument(
        "--replay-auth", action="store_true",
        help="serve the capture's recorded handshake verbatim instead of substituting a none-auth "
        "one. For a bug in the auth negotiation itself: it makes the replay need a client "
        "configured exactly like the original, and a scrubbed VNC challenge cannot be answered",
    )
    parser.add_argument(
        "--client-timeout", type=float, default=DEFAULT_CLIENT_TIMEOUT, metavar="SECONDS",
        help=f"warn if the client sends nothing for this long (default {DEFAULT_CLIENT_TIMEOUT})",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="hexdump client->server bytes")
    parser.add_argument(
        "--forever", action="store_true",
        help="--no-client only: keep accepting a new client after each connection ends",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="replay_capture: %(levelname)s: %(message)s",
    )

    is_capture = zipfile.is_zipfile(args.target)
    fork_client = is_capture and not args.no_client
    if args.forever and fork_client:
        parser.error("--forever keeps serving new clients, so it only makes sense with --no-client")

    try:
        if is_capture:
            factory = ReplayFactory(
                capture=load_capture(args.target),
                replay_auth=args.replay_auth,
                client_timeout=args.client_timeout,
                forever=args.forever,
            )
            if factory.replay_auth:
                if not args.replay_auth:
                    log.warning(
                        "cannot tell where this capture's handshake ends (no usable c2s.bin), "
                        "so its recorded auth is being replayed verbatim rather than substituted"
                    )
                for warning in scrub_warnings(factory.handshake.security_type):
                    log.warning("%s", warning)
        else:
            factory = ReplayFactory(
                messages=load_script(args.target),
                client_timeout=args.client_timeout,
                forever=args.forever,
            )
    except ValueError as exc:
        parser.error(str(exc))

    reactor.listenTCP(args.listen, factory, interface=args.bind)
    log.info("listening on %s:%s", args.bind, args.listen)

    client = None
    if fork_client:
        workdir = args.workdir or tempfile.mkdtemp(prefix="replay-capture-")
        os.makedirs(workdir, exist_ok=True)
        factory.stop_on_disconnect = False
        try:
            client = spawn_client(
                client_script(factory.capture.session_vdo, args.screenshot),
                workdir,
                f"{args.bind}::{args.listen}",
            )
        except ValueError as exc:
            parser.error(str(exc))

    reactor.run()
    return 0 if client is None else (client.exit_code or 0)


if __name__ == "__main__":
    sys.exit(main())
