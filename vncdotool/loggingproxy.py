from __future__ import annotations

import io
import logging
import os.path
import shlex
import socket
import sys
import time
from struct import unpack, unpack_from
from typing import IO, Callable, Sequence

from twisted.internet.error import ReactorNotRunning
from twisted.internet.protocol import Protocol
from twisted.protocols import portforward
from twisted.python.failure import Failure

from . import __version__ as VNCDOTOOL_VERSION
from .capture import CaptureWriter, HandshakeScrubber
from .const import AuthTypes, Encoding, MsgC2S, QemuClientMessage
from .client import VNCDoToolClient
from .keys import KEYMAP
from .rfb import PixelFormat, Rect

log = logging.getLogger(__name__)


class ProtocolError(Exception):
    """VNC Protocol error"""


TYPE_LEN = {
    MsgC2S.SET_PIXEL_FORMAT: 20,
    MsgC2S.SET_ENCODING: 4,
    MsgC2S.FRAMEBUFFER_UPDATE_REQUEST: 10,
    MsgC2S.KEY_EVENT: 8,
    MsgC2S.POINTER_EVENT: 6,
    MsgC2S.QEMU_CLIENT_MESSAGE: 1,
}

REVERSE_MAP = {v: n for (n, v) in KEYMAP.items()}


class RFBServer(Protocol):  # type: ignore[misc]
    _handler: tuple[Callable[..., None], int] = (lambda data: None, 0)

    def connectionMade(self) -> None:
        super().connectionMade()
        self.transport.setTcpNoDelay(True)

        self.buffer = bytearray()
        # XXX send version message
        self._handler = self._handle_version, 12

    def dataReceived(self, data: bytes) -> None:
        self.buffer += data
        while len(self.buffer) >= self._handler[1]:
            self._handler[0]()

    def _handle_version(self) -> None:
        msg = self.buffer[:12]
        del self.buffer[:12]
        if not msg.startswith(b"RFB 003.") and msg.endswith(b"\n"):
            self.transport.loseConnection()

        version = msg[8:11]
        if version in (b"003", b"005"):
            if self.factory.password_required:
                self._handler = self._handle_VNCAuthResponse, 16
            else:
                self._handler = self._handle_clientInit, 1
        elif version in (b"007", b"008"):
            # XXX send security v3.7+
            self._handler = self._handle_security, 1

    def _handle_security(self) -> None:
        sectype = self.buffer[0]
        log.debug("Client selected %r", AuthTypes.lookup(sectype))
        del self.buffer[:1]
        if sectype == AuthTypes.VNC_AUTHENTICATION:
            # The challenge/response is the same 16 bytes as on the pre-3.7
            # path, and must be skipped the same way: otherwise the response's
            # first byte is read as ClientInit's `shared` flag and everything
            # downstream desyncs.
            self._handler = self._handle_VNCAuthResponse, 16
        else:
            self._handler = self._handle_clientInit, 1

    def _handle_VNCAuthResponse(self) -> None:
        del self.buffer[:16]
        self._handler = self._handle_clientInit, 1

    def _handle_clientInit(self) -> None:
        shared = self.buffer[0]
        log.debug("Client shares: %s", shared)
        del self.buffer[:1]
        # XXX react to shared
        # XXX send serverInit
        self._handler = self._handle_protocol, 1

    def _handle_protocol(self) -> None:
        (ptype,) = unpack_from("!B", self.buffer)
        nbytes = TYPE_LEN.get(ptype, 0)
        if len(self.buffer) < nbytes:
            self._handler = self._handle_protocol, nbytes + 1
            return

        block = bytes(self.buffer[1:nbytes])
        del self.buffer[:nbytes]
        if ptype == MsgC2S.SET_PIXEL_FORMAT:
            (args,) = unpack("!xxx16s", block)
            pixel_fomat = PixelFormat.from_bytes(args)
            self.handle_setPixelFormat(pixel_fomat)
        elif ptype == MsgC2S.SET_ENCODING:
            (nencodings,) = unpack("!xH", block)
            nbytes = 4 * nencodings
            encodings = unpack_from("!" + "I" * nencodings, self.buffer)
            del self.buffer[:nbytes]
            for encoding in encodings:
                log.debug(f"Client announces {Encoding.lookup(encoding)!r}")
            self.handle_setEncodings(encodings)
        elif ptype == MsgC2S.FRAMEBUFFER_UPDATE_REQUEST:
            inc, x, y, w, h = unpack("!BHHHH", block)
            self.handle_framebufferUpdate(x, y, w, h, inc)
        elif ptype == MsgC2S.KEY_EVENT:
            down, key = unpack("!BxxI", block)
            self.handle_keyEvent(key, down)
        elif ptype == MsgC2S.POINTER_EVENT:
            buttonmask, x, y = unpack("!BHH", block)
            self.handle_pointerEvent(x, y, buttonmask)
        elif ptype == MsgC2S.CLIENT_CUT_TEXT:
            self.handle_clientCutText(block)
        elif ptype == MsgC2S.QEMU_CLIENT_MESSAGE:
            (subtype,) = unpack("!B", block)
            if subtype == QemuClientMessage.EXTENDED_KEY_EVENT:
                self._handler = self._handle_qemuExtendedKeyEvent, 10
            else:
                log.debug("Unhandled subtype %r", QemuClientMessage.lookup(subtype))
                raise ProtocolError(subtype)
        else:
            log.debug("Unhandled response %r", MsgC2S.lookup(ptype))
            raise ProtocolError(ptype)

    def _handle_qemuExtendedKeyEvent(self) -> None:
        down_flag, keysym, keycode = unpack_from("!HII", self.buffer)
        del self.buffer[:12]
        self.handle_keyEventExtended(keysym, down_flag, keycode)
        self._handler = self._handle_protocol, 1

    def handle_setPixelFormat(self, pixel_format: PixelFormat) -> None:
        pass

    def handle_setEncodings(self, encodings: Sequence[int]) -> None:
        pass

    def handle_framebufferUpdate(
        self, x: int, y: int, w: int, h: int, incremental: bool
    ) -> None:
        pass

    def handle_keyEvent(self, key: int, down: bool) -> None:
        pass

    def handle_pointerEvent(self, x: int, y: int, buttonmask: int) -> None:
        pass

    def handle_clientCutText(self, block: bytes) -> None:
        pass

    def handle_keyEventExtended(self, keysym: int, down: bool, keycode: int) -> None:
        self.handle_keyEvent(keysym, down)


class NullTransport:
    addressFamily = socket.AF_UNSPEC

    def write(self, data: bytes) -> None:
        return

    def writeSequence(self, data: bytes) -> None:
        return

    def setTcpNoDelay(self, enabled: bool) -> None:
        return

    def loseConnection(self) -> None:
        return


class VNCLoggingClient(VNCDoToolClient):
    """Specialization of a :class:`VNCDoToolClient` that will save screen captures."""

    capture_file: str | None = None
    capture: CaptureWriter | None = None

    def _handleRectangle(self, block: bytes) -> None:
        # Tallied off the decoded stream: SetEncodings only says what the
        # client asked for, and a server may ignore it.
        if self.capture is not None:
            (encoding,) = unpack("!i", block[8:12])
            self.capture.note_encoding(encoding)
        super()._handleRectangle(block)

    def commitUpdate(self, rectangles: list[Rect] | None = None) -> None:
        if self.capture_file:
            assert self.screen is not None
            self.screen.save(self.capture_file)
            self.recorder("expect %s\n" % self.capture_file)
            self.capture_file = None


class VNCLoggingClientProxy(portforward.ProxyClient):  # type: ignore[misc]
    """Accept data from a server and forward to logger and downstream client.

    ::

        VNC server -> VNCLoggingClientProxy -> VNC client
                                            -> VNCLoggingClient
    """

    vnclog: VNCLoggingClient | None = None
    ncaptures = 0

    def startLogging(self, peer: VNCLoggingServerProxy) -> None:
        self.vnclog = VNCLoggingClient()
        self.vnclog.transport = NullTransport()
        self.vnclog.factory = self.peer.factory
        self.vnclog.recorder = peer.recorder
        self.vnclog.capture = peer.capture
        # XXX double call to connectionMade?
        self.vnclog.connectionMade()
        self.vnclog._handler = self.vnclog._handleExpected
        self.vnclog.expect(self.vnclog._handleServerInit, 24)

    def dataReceived(self, data: bytes) -> None:
        # Capture first: a parse failure below must never truncate it.
        if self.peer is not None and data:
            self.peer.saw_bytes = True
        if self.peer is not None and self.peer.capture is not None:
            self.peer.capture.feed_s2c(data)
            # Pre-3.7 the *server* picks the security type, so an
            # unscrubbable one surfaces on this side of the proxy.
            if self.peer.capture.abort_reason is not None:
                self.peer._abortCapture(self.peer.capture.abort_reason)
                return
        if self.vnclog:
            # The decoder is an observer: it feeds the log, never the client.
            # Killing a session the server was happy with, because our own
            # optional logging choked, would record a vnclog artefact.
            try:
                self.vnclog.dataReceived(data)
            except Exception:
                log.warning(
                    "vnclog client failed to parse %d server bytes; forwarding continues",
                    len(data), exc_info=True,
                )
        # Forwarding is not wrapped: if bytes cannot reach the client, the
        # session has to fail like it always did rather than hang.
        super().dataReceived(data)


class VNCLoggingClientFactory(portforward.ProxyClientFactory):  # type: ignore[misc]
    protocol = VNCLoggingClientProxy


class VNCLoggingServerProxy(portforward.ProxyServer, RFBServer):  # type: ignore[misc]
    """Proxy in the middle, decodes and logs RFB messages before sending them upstream.

    ::

        VNC client -> VNCLoggingServerProxy -> VNC server
                                            -> RFBServer
    """

    clientProtocolFactory = VNCLoggingClientFactory

    server: str | None = None
    buttons = 0
    recorder: Callable[[str], int] | None = None
    capture: CaptureWriter | None = None
    saw_bytes: bool = False
    # A refused connection owns nothing: it never ran ProxyServer's
    # connectionMade, so it has no peer, no recorder and no claim to release.
    # It can still receive bytes -- pauseProducing() is part of the setup it
    # skipped -- so every later hook has to check this first.
    refused: bool = False
    took_session: bool = False

    def connectionMade(self) -> None:
        # Taken on accept rather than on first byte, so a second concurrent
        # connection is refused rather than interleaved into the session.
        if self.factory.one_shot and self.factory.session_taken:
            log.warning(
                "--one-shot: already serving a session; refusing connection from %s",
                self.transport.getPeer().host,
            )
            self.refused = True
            self.transport.loseConnection()
            return

        log.info("new connection from %s", self.transport.getPeer().host)
        super().connectionMade()
        RFBServer.connectionMade(self)
        self.mouse: tuple[int | None, int | None] = (None, None)
        self.last_event = time.time()
        self.recorder = self.factory.getRecorder()
        if self.factory.one_shot:
            self.factory.session_taken = True
            self.took_session = True
        if self.factory.capture_path:
            self.capture = CaptureWriter(
                server=self.factory.server_address,
                scrubber=HandshakeScrubber(preserve_auth=self.factory.capture_preserve_auth),
            )

    def connectionLost(self, reason: Failure) -> None:
        if self.refused:
            # Touching the factory here would release the live session's
            # claim, or close the recorder it is still writing to.
            return

        # Bytes in either direction make it a session, including a server
        # rejecting the client before it speaks -- that rejection is itself
        # the evidence. A bare TCP open/close is not one, so a port probe
        # neither writes a capture nor uses up a --one-shot run.
        if self.saw_bytes:
            try:
                if self.capture is not None:
                    self._writeCapture()
            except Exception:
                log.error("--capture-raw: could not write %s", self.factory.capture_path, exc_info=True)
                self.factory.capture_failed = True
            finally:
                # Even a failed write has to end a --one-shot run: the
                # alternative is a process that never exits.
                if self.factory.one_shot:
                    self.factory.sessionFinished()
        else:
            log.debug("connection produced no bytes; not counting it as a session")
            if self.took_session:
                self.factory.session_taken = False
            self.capture = None
        super().connectionLost(reason)
        self.factory.clientConnectionLost(self)

    def _writeCapture(self) -> None:
        assert self.capture is not None
        capture_path = self.factory.capture_path
        assert capture_path is not None
        self.capture.write_archive(
            capture_path,
            self.capture.meta(VNCDOTOOL_VERSION),
            session_vdo=self.factory.getRecordedSession(),
        )
        log.info("--capture-raw: wrote %s", capture_path)
        # Guard against a double connectionLost (peer already gone) writing twice.
        self.capture = None

    def _abortCapture(self, reason: str) -> None:
        """Drop an in-flight capture we are not allowed to write."""
        log.error("--capture-raw aborted: %s", reason)
        self.factory.capture_failed = True
        self.capture = None
        if self.vnclog_client is not None:
            self.vnclog_client.capture = None
        self.transport.loseConnection()

    @property
    def vnclog_client(self) -> VNCLoggingClient | None:
        peer = getattr(self, "peer", None)
        return getattr(peer, "vnclog", None) if peer is not None else None

    def dataReceived(self, data: bytes) -> None:
        if self.refused:
            # loseConnection() is not instant and this connection never got
            # ProxyServer's pauseProducing(), so bytes can still arrive.
            return

        # Capture first: a parse failure below must never truncate it.
        if data:
            self.saw_bytes = True
        if self.capture is not None:
            self.capture.feed_c2s(data)
            if self.capture.abort_reason is not None:
                self._abortCapture(self.capture.abort_reason)
                return
        # See VNCLoggingClientProxy.dataReceived: the semantic parser is an
        # observer, the forwarding is not.
        try:
            RFBServer.dataReceived(self, data)
        except Exception:
            log.warning(
                "RFBServer failed to parse %d client bytes; forwarding continues",
                len(data), exc_info=True,
            )
        super().dataReceived(data)

    def _handle_clientInit(self) -> None:
        RFBServer._handle_clientInit(self)
        self.peer.startLogging(self)

    def handle_keyEvent(self, key: int, down: bool) -> None:
        now = time.time()

        # Unmapped keysyms fall back to a raw char (', ", #, \) that shlex
        # would otherwise treat as quoting or a comment on replay.
        rev = shlex.quote(REVERSE_MAP.get(key, chr(key)))

        cmds = ["pause", "%.4f" % (now - self.last_event)]
        self.last_event = now
        if down:
            cmds += "keydown", rev
        else:
            cmds += "keyup", rev
        cmds.append("\n")
        assert self.recorder is not None
        self.recorder(" ".join(cmds))

    def handle_pointerEvent(self, x: int, y: int, buttonmask: int) -> None:
        now = time.time()

        cmds = ["pause", "%.4f" % (now - self.last_event)]
        self.last_event = now
        if self.mouse != (x, y):
            cmds.append("move %d %d" % (x, y))
            self.mouse = x, y

        for button in range(1, 9):
            if buttonmask & (1 << (button - 1)):
                cmds.append("click %d" % button)
        cmds.append("\n")
        assert self.recorder is not None
        self.recorder(" ".join(cmds))


class VNCLoggingServerFactory(portforward.ProxyFactory):  # type: ignore[misc]
    protocol = VNCLoggingServerProxy
    shared = True

    pseudocursor = False
    nocursor = False
    pseudodesktop = True
    qemu_extended_key = True
    last_rect = True
    force_caps = False

    password_required = False
    password: str | None = None

    output: IO[str] | str = sys.stdout
    _out: IO[str] | None = None

    one_shot: bool = False
    session_taken: bool = False

    capture_path: str | None = None
    capture_preserve_auth: bool = False
    # Aborted or unwritable: read by the CLI to pick a non-zero exit status.
    capture_failed: bool = False
    server_address: str = ""
    _capture_vdo: io.StringIO | None = None

    def sessionFinished(self) -> None:
        """End the process after a --one-shot session, once it has closed."""
        from twisted.internet import reactor

        log.info("--one-shot: session finished, shutting down")
        try:
            reactor.stop()
        except ReactorNotRunning:
            pass

    def getRecorder(self) -> Callable[[str], int]:
        if self.capture_path:
            # Buffered: the session log is one member of the archive, so
            # nothing lands on disk until the whole capture is writable.
            self._capture_vdo = io.StringIO()
            return self._capture_vdo.write
        elif isinstance(self.output, str):
            now = time.strftime("%y%m%d-%H%M%S")
            outfile = os.path.join(self.output, "%s.vdo" % now)
            self._out = open(outfile, "w")
            return self._out.write
        else:
            return self.output.write

    def getRecordedSession(self) -> bytes:
        return self._capture_vdo.getvalue().encode() if self._capture_vdo else b""

    def clientConnectionMade(self, client: VNCLoggingServerProxy) -> None:
        pass

    def clientConnectionLost(self, client: VNCLoggingServerProxy) -> None:
        if self._out:
            self._out.close()
            self._out = None
        self._capture_vdo = None
