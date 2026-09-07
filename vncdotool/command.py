#!/usr/bin/env python
"""
Command line interface to interact with a VNC Server.
"""
# (c) 2010-2024 Marc Sibson
#
# MIT License

from __future__ import annotations

import argparse
import getpass
import ipaddress
import enum
import logging
import logging.handlers
import os
import shlex
import socket
import sys
import tempfile
from types import TracebackType

from twisted.internet import protocol, reactor
from twisted.internet.error import ConnectError, ConnectionClosed, DNSLookupError
from twisted.internet.interfaces import IConnector
from twisted.python.failure import Failure
from twisted.python.log import PythonLoggingObserver

from . import decoders, pixelformat, websocket
from .capture import check_capture_target
from .client import (
    JPEG_QUALITY_ENCODINGS,
    AuthenticationError,
    ProtocolError,
    TClient,
    VNCDoToolClient,
    VNCDoToolFactory,
    factory_connect,
)
from .loggingproxy import VNCLoggingServerFactory
from .replay import Capture

log = logging.getLogger()

SUPPORTED_FORMATS = ("png", "jpg", "jpeg", "gif", "bmp")

# A JPEG frame is further from its target than any per-pixel bound can
# separate from a wrong screen; asking for a quality level asks for this too.
LOSSY_BLUR = 2


class TimeoutError(RuntimeError):
    pass


class ExitStatus(enum.IntEnum):
    """Exit codes returned by :program:`vncdo`, grouped by cause."""

    SUCCESS = 0
    ERROR = 1
    # bad input from whoever invoked us, credentials included
    USAGE = 2
    AUTHENTICATION_FAILED = 3

    CONNECTION_FAILED = 10
    CONNECTION_LOST = 11

    PROTOCOL_ERROR = 20

    COMMAND_FAILED = 30

    TIMEOUT = 40


# more specific causes first; the first match decides the exit status
EXIT_STATUS_FOR_ERROR: dict[type[BaseException], ExitStatus] = {
    AuthenticationError: ExitStatus.AUTHENTICATION_FAILED,
    ProtocolError: ExitStatus.PROTOCOL_ERROR,
    TimeoutError: ExitStatus.TIMEOUT,
    ConnectError: ExitStatus.CONNECTION_FAILED,
    DNSLookupError: ExitStatus.CONNECTION_FAILED,
    ConnectionClosed: ExitStatus.CONNECTION_LOST,
}


def log_exceptions(
    type_: type[BaseException], value: BaseException, tb: TracebackType | None
) -> None:
    log.critical("Unhandled exception:", exc_info=(type_, value, tb))


def log_connected(pcol: TClient) -> TClient:
    log.info("connected to %s", pcol.name)
    return pcol


class VNCDoCLIClient(VNCDoToolClient):
    factory: VNCDoCLIFactory

    def vncRequestPassword(self) -> None:
        if self.factory.password is None:
            self.factory.password = getpass.getpass("VNC password:")

        self.sendPassword(self.factory.password)


class VNCDoCLIFactory(VNCDoToolFactory):
    protocol = VNCDoCLIClient

    def clientConnectionLost(self, connector: IConnector, reason: Failure) -> None:
        # losing the connection is never itself a success: the command chain
        # reports the outcome, and closing the transport is its last step, so
        # a close arriving first means the commands never finished
        self.error(reason, ExitStatus.CONNECTION_LOST)

    def clientConnectionFailed(self, connector: IConnector, reason: Failure) -> None:
        self.error(reason, ExitStatus.CONNECTION_FAILED)

    def error(
        self, reason: Failure, default: ExitStatus = ExitStatus.COMMAND_FAILED
    ) -> None:
        if reactor.exit_status is not None:
            return
        print(reason.getErrorMessage(), file=sys.stderr)
        log.debug(reason.getTraceback())
        self.done(self.status_for(reason, default))

    @staticmethod
    def status_for(reason: Failure, default: ExitStatus) -> ExitStatus:
        for error_type, status in EXIT_STATUS_FOR_ERROR.items():
            if reason.check(error_type):
                return status
        return default

    def done(self, exit_code: ExitStatus) -> None:
        # first outcome wins; the expected close follows a completed run
        if reactor.exit_status is not None:
            return
        reactor.exit_status = exit_code
        reactor.callLater(0.1, reactor.stop)


class ExitingProcess(protocol.ProcessProtocol):
    def processExited(self, reason: Failure) -> None:
        reactor.callLater(0.1, reactor.stop)

    def errReceived(self, data: bytes) -> None:
        sys.stderr.buffer.write(data)
        sys.stderr.buffer.flush()


class VNCDoToolArgumentParser(argparse.ArgumentParser):
    def format_help(self) -> str:
        result = super().format_help()
        result += (
            "\n"
            "Common Commands (CMD):\n"
            "  key KEY\t\tsend KEY to server, alphanumeric or keysym: ctrl-c, del\n"
            "  type TEXT\t\tsend alphanumeric string of TEXT\n"
            "  typefile FILENAME\t\ttype out the contents of FILENAME\n"
            "  move X Y\t\tmove the mouse cursor to position X,Y\n"
            "  click BUTTON\t\tsend a mouse BUTTON click\n"
            "  capture FILE\t\tsave current screen as FILE\n"
            "  expect FILE [FUZZ]\twait until screen matches FILE\n"
            "  stable SECONDS [FUZZ]\twait until screen stops changing\n"
            "  pause SECONDS\t\twait SECONDS before sending next command\n"
            "\n"
            "Other Commands (CMD):\n"
            "  keyup KEY\t\tsend KEY released\n"
            "  keydown KEY\t\tsend KEY pressed\n"
            "  mousedown BUTTON\tsend BUTTON down\n"
            "  mousemove X Y\t\talias for move\n"
            "  mouseup BUTTON\tsend BUTTON up\n"
            "  drag X Y\t\tmove the mouse to X,Y in small steps\n"
            "  rcapture FILE X Y W H\tcapture a region of the screen\n"
            "  rexpect FILE X Y [FUZZ]\texpect that matches a region of the screen\n"
            "  rstable SECONDS X Y W H [FUZZ]\tstable for a region of the screen\n"
            "\n"
            "If a filename is given commands will be read from it, or stdin `-`\n"
        )
        return result


class CommandParseError(RuntimeError):
    pass


def _trailing_fuzz(args: list[str], cmd: str = "expect") -> int | None:
    if not args:
        return None
    try:
        # Parsed as a float so that a script written against the old metric,
        # which took one, says what is wrong with it rather than having its
        # number read as the next command.
        fuzz = float(args[0])
    except ValueError:
        return None
    written = args.pop(0)
    if fuzz != int(fuzz) or not 0 <= fuzz <= 255:
        raise CommandParseError(
            f"{cmd} takes a whole-number fuzz from 0 (exact) to 255, not {written}"
        )
    return int(fuzz)


def build_command_list(
    factory: VNCDoCLIFactory,
    args: list[str],
    delay: float | None = None,
    warp: float = 1.0,
    incremental_refreshes: bool = False,
) -> None:
    client = VNCDoCLIClient

    if delay:
        delay = float(delay) / 1000.0

    while args:
        cmd = args.pop(0)
        if cmd == "key":
            key = args.pop(0)
            factory.deferred.addCallback(client.keyPress, key)
        elif cmd in ("kdown", "keydown"):
            key = args.pop(0)
            factory.deferred.addCallback(client.keyDown, key)
        elif cmd in ("kup", "keyup"):
            key = args.pop(0)
            factory.deferred.addCallback(client.keyUp, key)
        elif cmd in ("move", "mousemove"):
            x, y = int(args.pop(0)), int(args.pop(0))
            factory.deferred.addCallback(client.mouseMove, x, y)
        elif cmd == "click":
            button = int(args.pop(0))
            factory.deferred.addCallback(client.mousePress, button)
        elif cmd in ("mdown", "mousedown"):
            button = int(args.pop(0))
            factory.deferred.addCallback(client.mouseDown, button)
        elif cmd in ("mup", "mouseup"):
            button = int(args.pop(0))
            factory.deferred.addCallback(client.mouseUp, button)
        elif cmd == "type":
            for key in args.pop(0):
                if key == "-":
                    key = "minus"
                factory.deferred.addCallback(client.keyPress, key)
                if delay:
                    factory.deferred.addCallback(client.pause, delay)
        elif cmd == "typefile":
            filename = args.pop(0)
            with open(filename) if filename != "-" else sys.stdin as f:
                content = f.read()
                for key in content:
                    if key == "\r":
                        continue
                    if key == "\n":
                        key = "enter"
                    if key == "\t":
                        key = "tab"
                    if key == "-":
                        key = "minus"
                    factory.deferred.addCallback(client.keyPress, key)
                    if delay:
                        factory.deferred.addCallback(client.pause, delay)
        elif cmd == "pastefile":
            filename = args.pop(0)
            with open(filename) if filename != "-" else sys.stdin as f:
                content = f.read().replace("\r\n", "\n")
                factory.deferred.addCallback(client.paste, content)
        elif cmd == "capture":
            filename = args.pop(0)
            imgformat = os.path.splitext(filename)[1][1:]
            if imgformat not in SUPPORTED_FORMATS:
                raise CommandParseError(
                    f'unsupported image format "{imgformat}", choose one of {SUPPORTED_FORMATS}'
                )
            factory.deferred.addCallback(
                client.captureScreen, filename, int(incremental_refreshes)
            )
        elif cmd == "expect":
            filename = args.pop(0)
            factory.deferred.addCallback(
                client.expectScreen, filename, _trailing_fuzz(args)
            )
        elif cmd == "rcapture":
            filename = args.pop(0)
            x = int(args.pop(0))
            y = int(args.pop(0))
            w = int(args.pop(0))
            h = int(args.pop(0))
            imgformat = os.path.splitext(filename)[1][1:]
            if imgformat not in SUPPORTED_FORMATS:
                raise CommandParseError(
                    f'unsupported image format "{imgformat}", choose one of {SUPPORTED_FORMATS}'
                )
            factory.deferred.addCallback(client.captureRegion, filename, x, y, w, h)
        elif cmd == "rexpect":
            filename = args.pop(0)
            x = int(args.pop(0))
            y = int(args.pop(0))
            factory.deferred.addCallback(
                client.expectRegion, filename, x, y, _trailing_fuzz(args)
            )
        elif cmd == "stable":
            seconds = float(args.pop(0))
            factory.deferred.addCallback(
                client.stableScreen, seconds, _trailing_fuzz(args, cmd)
            )
        elif cmd == "rstable":
            seconds = float(args.pop(0))
            x = int(args.pop(0))
            y = int(args.pop(0))
            w = int(args.pop(0))
            h = int(args.pop(0))
            factory.deferred.addCallback(
                client.stableRegion, seconds, x, y, w, h, _trailing_fuzz(args, cmd)
            )
        elif cmd in ("pause", "sleep"):
            duration = float(args.pop(0)) / warp
            factory.deferred.addCallback(client.pause, duration)
        elif cmd == "drag":
            x, y = int(args.pop(0)), int(args.pop(0))
            factory.deferred.addCallback(client.mouseDrag, x, y)
        elif os.path.isfile(cmd):
            lex = shlex.shlex(open(cmd), posix=True)
            lex.whitespace_split = True
            args = list(lex) + args
        else:
            raise CommandParseError('unknown cmd "%s"' % cmd)

        if delay and args:
            factory.deferred.addCallback(client.pause, delay)


def build_tool(options: argparse.Namespace, args: list[str]) -> VNCDoCLIFactory:
    factory = VNCDoCLIFactory()

    if options.verbose:
        factory.deferred.addCallbacks(log_connected)

    if args == ["-"]:
        lex = shlex.shlex(posix=True)
        lex.whitespace_split = True
        args = list(lex)

    try:
        build_command_list(
            factory, args, options.delay, options.warp, options.incremental_refreshes
        )
    except CommandParseError as exc:
        print(exc, file=sys.stderr)
        sys.exit(ExitStatus.USAGE)

    # no outcome decided yet; set before connecting so a synchronous
    # connection failure has somewhere to record itself
    reactor.exit_status = None
    try:
        factory_connect(factory, options.host, options.port, options.address_family)
    except websocket.WebSocketUnavailable as exc:
        print(exc, file=sys.stderr)
        sys.exit(ExitStatus.USAGE)

    factory.deferred.addCallback(lambda client: client.transport.loseConnection())
    factory.deferred.addCallback(lambda _: factory.done(ExitStatus.SUCCESS))
    factory.deferred.addErrback(factory.error)

    return factory


def build_proxy(options: argparse.Namespace) -> VNCLoggingServerFactory:
    factory = VNCLoggingServerFactory(options.host, int(options.port))
    factory.password_required = options.password_required
    factory.server_address = options.server
    port = reactor.listenTCP(options.listen, factory)
    reactor.exit_status = 0
    factory.listen_port = port.getHost().port

    return factory


def add_standard_options(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument(
        "-p",
        "--password",
        help="use password to access server",
    )
    parser.add_argument(
        "-u",
        "--username",
        help="use username to access server",
    )
    parser.add_argument(
        "-s",
        "--server",
        default="127.0.0.1",
        help="connect to VNC server at ADDRESS[:DISPLAY|::PORT], a Unix socket "
        "path, or a ws://HOST:PORT/PATH or wss:// URL [%(default)s]",
    )
    parser.add_argument(
        "--logfile",
        metavar="FILE",
        help="output logging information to FILE",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="increase verbosity, use multiple times",
    )
    # REMAINDER stops option parsing at the first positional, which is what
    # optparse's disable_interspersed_args did.
    parser.add_argument("args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    return parser


def trailing_args(options: argparse.Namespace) -> list[str]:
    """The command list, without the `--` that may have introduced it.

    argparse hands REMAINDER the `--` that ended option parsing; optparse
    dropped it, and a command list starting with `--` is not a command.
    """
    args = options.args
    return args[1:] if args and args[0] == "--" else args


def setup_logging(options: argparse.Namespace) -> None:
    # route Twisted log messages via stdlib logging
    if options.logfile:
        handler = logging.handlers.RotatingFileHandler(
            options.logfile, maxBytes=5 << 20, backupCount=5
        )
        logging.getLogger().addHandler(handler)
        sys.excepthook = log_exceptions

    logging.basicConfig(format="%(levelname)s: %(message)s")
    if options.verbose > 1:
        logging.getLogger().setLevel(logging.DEBUG)
    elif options.verbose:
        logging.getLogger().setLevel(logging.INFO)

    PythonLoggingObserver().start()


def format_address(host: str, port: int) -> str:
    """Render a parsed address for a log line, with any URL credentials removed."""
    if websocket.is_websocket_url(host):
        return websocket.redact(host)
    return f"{host}:{port}"


def parse_server(server: str) -> tuple[websocket.AddressFamily, str, int]:
    if websocket.is_websocket_url(server):
        url, port = websocket.parse_url(server)
        return websocket.WEBSOCKET, url, port

    if server.startswith("["):
        host, sep, server = server[1:].partition("]")
        if not sep:
            raise ValueError(server)
        ipaddress.IPv6Address(host)
        split = server.split(":")
        address_family = socket.AF_INET6
    else:
        split = server.split(":")
        if not split[0]:
            host = "127.0.0.1"
        else:
            host = split[0]

        if hasattr(socket, "AF_UNIX") and os.path.exists(host):
            address_family = socket.AF_UNIX
        else:
            try:
                ipaddress.IPv4Address(host)
            except ipaddress.AddressValueError:
                address_family = socket.AF_UNSPEC
            else:
                address_family = socket.AF_INET

    if len(split) == 3:  # ::port
        port = int(split[2])
    elif len(split) == 2:  # :display
        port = int(split[1]) + 5900
    elif len(split) == 1:  # default
        port = 5900
    else:
        raise ValueError(server)

    return address_family, host, port


def vnclog() -> None:
    from vncdotool import __version__

    usage = "%(prog)s [options] [OUTPUT]"
    description = "Capture user interactions with a VNC Server"

    parser = argparse.ArgumentParser(usage=usage, description=description)
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    add_standard_options(parser)
    parser.add_argument(
        "--listen",
        metavar="PORT",
        default=5902,
        type=int,
        help="listen for client connections on PORT [%(default)s]",
    )
    parser.add_argument(
        "--file-per-client",
        action="store_true",
        default=False,
        help="record each client connection to its own .vdo in OUTPUT, which must "
        "be a directory (was --forever, which never controlled how long vnclog ran)",
    )
    parser.add_argument(
        "--viewer",
        metavar="CMD",
        help="launch an interactive client using CMD [%(default)s]",
    )
    # ideally we wouldn't need this, VNCLoggingClient should sniff and set this properly
    parser.add_argument(
        "--password-required",
        action="store_true",
        default=False,
        help="a VNC password is required to connect to the server",
    )
    parser.add_argument(
        "--one-shot",
        action="store_true",
        default=False,
        help="serve a single session, then exit; implied by --capture-raw",
    )
    parser.add_argument(
        "--capture-raw",
        metavar="FILE.zip",
        help="write a raw wire capture (auth stripped, replaced by a none-auth "
        "handshake) to FILE.zip, ready to attach to an issue -- see docs/capture.rst. "
        "FILE.zip must not exist; OUTPUT is implied (session.vdo inside the archive) "
        "and should be omitted.",
    )
    parser.add_argument(
        "--capture-raw-unsafe",
        action="store_true",
        default=False,
        help="record the handshake verbatim instead of stripping it, credential exchange "
        "and all. Needed for auth types vncdotool cannot follow, and for a bug in the "
        "negotiation itself. Use a disposable password and rotate it afterwards.",
    )
    options = parser.parse_args()
    args = trailing_args(options)

    setup_logging(options)

    options.address_family, options.host, options.port = parse_server(options.server)
    if options.address_family is websocket.WEBSOCKET:
        parser.error("vnclog records a TCP or Unix-socket server; ws:// is vncdo-only")

    output = None
    # The error names only --one-shot; --capture-raw implies it.
    if (options.one_shot or options.capture_raw) and options.file_per_client:
        parser.error("--file-per-client records several clients, so it cannot be combined with --one-shot")
    if options.capture_raw:
        if args:
            parser.error("OUTPUT is implied by --capture-raw (session.vdo in the archive); do not also pass OUTPUT")
        try:
            check_capture_target(options.capture_raw)
        except ValueError as exc:
            parser.error(str(exc))
    elif options.capture_raw_unsafe:
        parser.error("--capture-raw-unsafe is only meaningful with --capture-raw")
    elif len(args) != 1:
        parser.error("incorrect number of arguments")
    else:
        output = args[0]

    factory = build_proxy(options)
    # stderr, because stdout may carry the recorded session (OUTPUT of `-`)
    print(
        f"accepting connections on ::{factory.listen_port}",
        file=sys.stderr,
        flush=True,
    )

    factory.one_shot = options.one_shot or bool(options.capture_raw)

    if options.capture_raw:
        factory.capture_path = options.capture_raw
        factory.capture_preserve_auth = options.capture_raw_unsafe
    elif options.file_per_client and os.path.isdir(output):
        factory.output = output
    elif options.file_per_client:
        parser.error("--file-per-client requires OUTPUT to be a directory")
    elif output == "-":
        factory.output = sys.stdout
    else:
        factory.output = open(output, "w")

    factory.password = options.password

    if options.viewer:
        cmdline = f"{options.viewer} localhost::{factory.listen_port}"
        reactor.spawnProcess(
            ExitingProcess(),
            options.viewer,
            cmdline.split(),
            env=os.environ,
        )
    reactor.run()
    if factory.capture_failed and not reactor.exit_status:
        # Aborted or unwritable capture: the contributor has no archive, so
        # exiting 0 would tell a script the capture succeeded.
        sys.exit(ExitStatus.COMMAND_FAILED)
    sys.exit(reactor.exit_status)


def vncdo(argv: list[str] | None = None) -> None:
    from vncdotool import __version__

    usage = "%(prog)s [options] CMD CMDARGS|-|filename"
    description = "Command line control of a VNC server"

    parser = VNCDoToolArgumentParser(usage=usage, description=description)
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    add_standard_options(parser)

    parser.add_argument(
        "--delay",
        metavar="MILLISECONDS",
        default=os.environ.get("VNCDOTOOL_DELAY", 10),
        type=int,
        help="delay MILLISECONDS between actions [%(default)sms]",
    )
    parser.add_argument(
        "--force-caps",
        action="store_true",
        help="for non-compliant servers, send shift-LETTER, ensures capitalization works",
    )
    parser.add_argument(
        "--localcursor",
        action="store_true",
        help="request the cursor shape from the server and draw it into captures",
    )
    parser.add_argument(
        "--nocursor",
        action="store_true",
        help="omit the mouse pointer from captures",
    )
    parser.add_argument(
        "--disable-desktop-resizing",
        action="store_true",
        help="disable desktop resizing, this was default behaviour < 0.11",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        metavar="SECONDS",
        help="abort if unable to complete all actions within TIMEOUT seconds",
    )
    parser.add_argument(
        "-w",
        "--warp",
        type=float,
        metavar="FACTOR",
        default=1.0,
        help="pause time is accelerated by FACTOR [x%(default)s]",
    )
    parser.add_argument(
        "--encodings",
        metavar="LIST",
        help="comma-separated encodings to offer the server, in preference "
        "order (%s) [%s]"
        % (
            ", ".join(decoders.ENCODING_NAMES),
            ",".join(decoders.DEFAULT_ENCODING_NAMES),
        ),
    )
    parser.add_argument(
        "--pixel-format",
        metavar="FORMAT",
        choices=sorted(pixelformat.PIXEL_FORMATS),
        help="ask the server for FORMAT (%s) instead of accepting the one it "
        "announces" % ", ".join(sorted(pixelformat.PIXEL_FORMATS)),
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        metavar="LEVEL",
        help="offer the JPEG Quality Level pseudo-encoding for LEVEL, 0 (low) "
        "to 9 (high). Lossy [none]",
    )
    parser.add_argument(
        "--fuzz",
        type=int,
        metavar="N",
        help="how far any one pixel may sit from the target image for expect "
        "or stable to call it a match, 0 (exact) to 255 [what the pixel "
        "format cannot express]",
    )
    parser.add_argument(
        "--blur",
        type=int,
        metavar="RADIUS",
        help="blur both screens by RADIUS before expect or stable compares "
        "them, which is what carries a match through a lossy encoding "
        "[%d with --jpeg-quality, 0 without]" % LOSSY_BLUR,
    )
    parser.add_argument(
        "-i",
        "--incremental-refreshes",
        action="store_true",
        default=False,
        help='set the "incremental" flag',
    )

    options = parser.parse_args(args=argv)
    args = trailing_args(options)
    if not len(args):
        parser.error("no command provided")

    setup_logging(options)
    options.address_family, options.host, options.port = parse_server(options.server)

    log.info("connecting to %s", format_address(options.host, options.port))

    factory = build_tool(options, args)
    factory.username = options.username
    factory.password = options.password

    if options.localcursor:
        factory.pseudocursor = True

    if options.disable_desktop_resizing:
        factory.pseudodesktop = False

    if options.nocursor:
        factory.nocursor = True

    if options.force_caps:
        factory.force_caps = True

    if options.encodings:
        try:
            factory.encodings = [
                decoders.ENCODING_NAMES[name.strip()]
                for name in options.encodings.split(",")
            ]
        except KeyError as exc:
            parser.error(f"unknown encoding {exc.args[0]!r}; known: {', '.join(decoders.ENCODING_NAMES)}")

    if options.pixel_format:
        factory.pixel_format = pixelformat.PIXEL_FORMATS[options.pixel_format]

    if options.jpeg_quality is not None:
        if options.jpeg_quality not in range(len(JPEG_QUALITY_ENCODINGS)):
            parser.error(
                f"--jpeg-quality takes a level from 0 (low) to "
                f"{len(JPEG_QUALITY_ENCODINGS) - 1} (high), not "
                f"{options.jpeg_quality}"
            )
        offered = factory.encodings or decoders.DEFAULT_ENCODINGS
        if decoders.ENCODING_NAMES["tight"] not in offered:
            parser.error("--jpeg-quality only applies to Tight; add --encodings tight")
        factory.jpeg_quality = options.jpeg_quality

    if options.fuzz is not None:
        if not 0 <= options.fuzz <= 255:
            parser.error(
                f"--fuzz takes a bound from 0 (exact) to 255, not "
                f"{options.fuzz}"
            )
        factory.fuzz = options.fuzz

    if options.blur is None:
        factory.blur = LOSSY_BLUR if options.jpeg_quality is not None else 0
    elif options.blur < 0:
        parser.error(f"--blur takes a radius of 0 or more, not {options.blur}")
    else:
        factory.blur = options.blur

    if options.timeout:
        message = "TIMEOUT Exceeded (%ss)" % options.timeout
        failure = Failure(TimeoutError(message))
        reactor.callLater(options.timeout, factory.error, failure)

    reactor.run()

    sys.exit(ExitStatus.ERROR if reactor.exit_status is None else reactor.exit_status)


def vncdo_replay() -> None:
    """Replay a `vnclog --capture-raw` archive: serve it, or drive it.

    Two processes: --server serves the recorded bytes, and any client (this
    command without --server, a GUI viewer, or a hand-written vncdo line)
    can drive the session against it. See docs/capture.rst."""
    from vncdotool import __version__
    from .replay import (
        DEFAULT_BIND,
        DEFAULT_CLIENT_TIMEOUT,
        DEFAULT_PORT,
        DEFAULT_SERVER,
        ReplayFactory,
        load_capture,
    )

    parser = VNCDoToolArgumentParser(
        usage="%(prog)s [options] CAPTURE.zip [CMD CMDARGS...]",
        description="Replay a vnclog --capture-raw archive. Without --server, runs the "
        "session.vdo recorded inside CAPTURE.zip through vncdo, plus any commands given "
        "after it. See docs/capture.rst.",
    )
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    parser.add_argument(
        "--server",
        action="store_true",
        default=False,
        help="serve the archive's recorded bytes to whatever client connects, instead of "
        "being the client",
    )
    parser.add_argument(
        "-s",
        "--connect",
        metavar="ADDRESS",
        default=DEFAULT_SERVER,
        help="client mode: the replay server to drive the session against [%(default)s]",
    )
    parser.add_argument(
        "-p",
        "--password",
        help="client mode: password for a --capture-raw-unsafe archive whose original "
        "handshake demands one",
    )
    parser.add_argument(
        "--listen",
        type=int,
        metavar="PORT",
        default=DEFAULT_PORT,
        help="--server: TCP port to listen on [%(default)s]",
    )
    parser.add_argument(
        "--bind",
        metavar="ADDR",
        default=DEFAULT_BIND,
        help="--server: interface to listen on [%(default)s], i.e. local connections only. A "
        "--capture-raw-unsafe archive replays whatever credentials it carried, so opening "
        "this up is a deliberate call to make.",
    )
    parser.add_argument(
        "--client-timeout",
        type=float,
        metavar="SECONDS",
        default=DEFAULT_CLIENT_TIMEOUT,
        help="--server: warn if the client sends nothing for this long, "
        "0 disables the warning [%(default)s]",
    )
    parser.add_argument(
        "--forever",
        action="store_true",
        default=False,
        help="--server: keep accepting a new client after each connection ends",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="hexdump client->server bytes")
    parser.add_argument("args", nargs="*", help=argparse.SUPPRESS)

    # argparse matches one contiguous run of positionals, so an option placed
    # after CAPTURE.zip leaves the commands behind it unmatched.
    options = parser.parse_args()
    args = options.args
    if not args:
        parser.error("no capture archive given")
    archive, extra = args[0], args[1:]

    logging.basicConfig(
        level=logging.DEBUG if options.verbose else logging.INFO,
        format="vncdo-replay: %(levelname)s: %(message)s",
    )

    try:
        capture = load_capture(archive)
    except ValueError as exc:
        parser.error(str(exc))

    if not options.server:
        _replay_client(parser, options, capture, archive, extra)
        return

    if extra:
        parser.error("--server serves bytes and takes no commands; run those from a client instead")
    if capture.auth_preserved:
        log.warning(
            "%s was recorded with --capture-raw-unsafe, so its original handshake is served "
            "verbatim: the client has to be configured the way the original one was, and "
            "whatever credentials that exchange carried are on the wire again",
            archive,
        )

    factory = ReplayFactory(
        capture=capture,
        client_timeout=options.client_timeout,
        forever=options.forever,
    )
    reactor.listenTCP(options.listen, factory, interface=options.bind)
    log.info("listening on %s:%s", options.bind, options.listen)
    reactor.run()


def _replay_client(
    parser: argparse.ArgumentParser,
    options: argparse.Namespace,
    capture: Capture,
    archive: str,
    extra: list[str],
) -> None:
    """Run the archive's recorded session through `vncdo`.

    Runs the archive's own recorded events rather than commands typed by
    hand: a replay driven by different input is a different session, which
    proves nothing about the one that was captured."""
    session_vdo = capture.session_vdo.strip()
    if not session_vdo and not extra:
        parser.error(
            f"{archive} records no session.vdo (a GUI-driven capture records events, not "
            "vncdo commands), and no commands were given to run instead"
        )
    if capture.auth_preserved:
        log.warning(
            "%s was recorded with --capture-raw-unsafe, so its original handshake demands "
            "real credentials again: pass -p/--password to match how the original client "
            "was configured, or the run will hang waiting for one",
            archive,
        )

    with tempfile.TemporaryDirectory(prefix="vncdo-replay-") as workdir:
        built_argv = ["-s", options.connect]
        if options.password:
            built_argv += ["-p", options.password]
        if session_vdo:
            script = os.path.join(workdir, "session.vdo")
            with open(script, "wb") as fh:
                fh.write(capture.session_vdo)
            built_argv.append(script)
        built_argv += extra
        vncdo(built_argv)


if __name__ == "__main__":
    vncdo()
