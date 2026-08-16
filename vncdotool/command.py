#!/usr/bin/env python
"""
Command line interface to interact with a VNC Server.
"""
# (c) 2010-2024 Marc Sibson
#
# MIT License

from __future__ import annotations

import getpass
import ipaddress
import enum
import logging
import logging.handlers
import optparse
import os
import shlex
import shutil
import socket
import sys
import tempfile
from types import TracebackType

from twisted.internet import protocol, reactor
from twisted.internet.error import ConnectError, ConnectionClosed, DNSLookupError
from twisted.internet.interfaces import IConnector
from twisted.python.failure import Failure
from twisted.python.log import PythonLoggingObserver

from .capture import check_capture_target
from .client import (
    AuthenticationError,
    ProtocolError,
    TClient,
    VNCDoToolClient,
    VNCDoToolFactory,
    factory_connect,
)
from .loggingproxy import VNCLoggingServerFactory

log = logging.getLogger()

SUPPORTED_FORMATS = ("png", "jpg", "jpeg", "gif", "bmp")


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
        log.critical(reason.getErrorMessage())
        self.done(self.status_for(reason, default))

    @staticmethod
    def status_for(reason: Failure, default: ExitStatus) -> ExitStatus:
        """Classify a failure, falling back to where it was reported from."""
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


class ExitingProcess(protocol.ProcessProtocol):  # type: ignore[misc]
    def processExited(self, reason: Failure) -> None:
        reactor.callLater(0.1, reactor.stop)

    def errReceived(self, data: bytes) -> None:
        sys.stderr.buffer.write(data)
        sys.stderr.buffer.flush()


class VNCDoToolOptionParser(optparse.OptionParser):
    def format_help(self, formatter: optparse.HelpFormatter | None = None) -> str:
        result = super().format_help(formatter)
        result += (
            "\n"
            "Common Commands (CMD):\n"
            "  key KEY\t\tsend KEY to server, alphanumeric or keysym: ctrl-c, del\n"
            "  type TEXT\t\tsend alphanumeric string of TEXT\n"
            "  typefile FILENAME\t\ttype out the contents of FILENAME\n"
            "  move X Y\t\tmove the mouse cursor to position X,Y\n"
            "  click BUTTON\t\tsend a mouse BUTTON click\n"
            "  capture FILE\t\tsave current screen as FILE\n"
            "  expect FILE FUZZ\twait until screen matches FILE\n"
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
            "  rexpect FILE X Y FUZZ\texpect that matches a region of the screen\n"
            "\n"
            "If a filename is given commands will be read from it, or stdin `-`\n"
        )
        return result


class CommandParseError(RuntimeError):
    pass


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
            rms = float(args.pop(0))
            factory.deferred.addCallback(client.expectScreen, filename, rms)
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
            rms = float(args.pop(0))
            factory.deferred.addCallback(client.expectRegion, filename, x, y, rms)
        elif cmd in ("pause", "sleep"):
            duration = float(args.pop(0)) / warp
            factory.deferred.addCallback(client.pause, duration)
        elif cmd in "drag":
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


def build_tool(options: optparse.Values, args: list[str]) -> VNCDoCLIFactory:
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
    factory_connect(factory, options.host, options.port, options.address_family)

    # close the connection when we're done, then report how it went
    factory.deferred.addCallback(lambda client: client.transport.loseConnection())
    factory.deferred.addCallback(lambda _: factory.done(ExitStatus.SUCCESS))
    factory.deferred.addErrback(factory.error)

    return factory


def build_proxy(options: optparse.Values) -> VNCLoggingServerFactory:
    factory = VNCLoggingServerFactory(options.host, int(options.port))
    factory.password_required = options.password_required
    factory.server_address = options.server
    port = reactor.listenTCP(options.listen, factory)
    reactor.exit_status = 0
    factory.listen_port = port.getHost().port

    return factory


def add_standard_options(parser: optparse.OptionParser) -> optparse.OptionParser:
    parser.disable_interspersed_args()

    parser.add_option(
        "-p",
        "--password",
        help="use password to access server",
    )
    parser.add_option(
        "-u",
        "--username",
        help="use username to access server",
    )
    parser.add_option(
        "-s",
        "--server",
        default="127.0.0.1",
        help="connect to VNC server at ADDRESS[:DISPLAY|::PORT] [%default]",
    )
    parser.add_option(
        "--logfile",
        metavar="FILE",
        help="output logging information to FILE",
    )
    parser.add_option(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="increase verbosity, use multiple times",
    )
    return parser


def setup_logging(options: optparse.Values) -> None:
    # route Twisted log messages via stdlib logging
    if options.logfile:
        handler = logging.handlers.RotatingFileHandler(
            options.logfile, maxBytes=5 << 20, backupCount=5
        )
        logging.getLogger().addHandler(handler)
        sys.excepthook = log_exceptions

    logging.basicConfig()
    if options.verbose > 1:
        logging.getLogger().setLevel(logging.DEBUG)
    elif options.verbose:
        logging.getLogger().setLevel(logging.INFO)

    PythonLoggingObserver().start()


def parse_server(server: str) -> tuple[socket.AddressFamily, str, int]:
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

    usage = "%prog [options] [OUTPUT]"
    description = "Capture user interactions with a VNC Server"
    version = "%prog " + __version__

    op = optparse.OptionParser(usage=usage, description=description, version=version)
    add_standard_options(op)
    op.add_option(
        "--listen",
        metavar="PORT",
        default=5902,
        type="int",
        help="listen for client connections on PORT [%default]",
    )
    op.add_option(
        "--file-per-client",
        action="store_true",
        default=False,
        help="record each client connection to its own .vdo in OUTPUT, which must "
        "be a directory (was --forever, which never controlled how long vnclog ran)",
    )
    op.add_option(
        "--viewer",
        metavar="CMD",
        help="launch an interactive client using CMD [%default]",
    )
    # ideally we wouldn't need this, VNCLoggingClient should sniff and set this properly
    op.add_option(
        "--password-required",
        action="store_true",
        default=False,
        help="a VNC password is required to connect to the server",
    )
    op.add_option(
        "--one-shot",
        action="store_true",
        default=False,
        help="serve a single session, then exit; implied by --capture-raw",
    )
    op.add_option(
        "--capture-raw",
        metavar="FILE.zip",
        help="write a raw wire capture (auth stripped, replaced by a none-auth "
        "handshake) to FILE.zip, ready to attach to an issue -- see docs/capture.rst. "
        "FILE.zip must not exist; OUTPUT is implied (session.vdo inside the archive) "
        "and should be omitted.",
    )
    op.add_option(
        "--capture-raw-unsafe",
        action="store_true",
        default=False,
        help="record the handshake verbatim instead of stripping it, credential exchange "
        "and all. Needed for auth types vncdotool cannot follow, and for a bug in the "
        "negotiation itself. Use a disposable password and rotate it afterwards.",
    )
    options, args = op.parse_args()

    setup_logging(options)

    options.address_family, options.host, options.port = parse_server(options.server)

    output = None
    # --capture-raw implies --one-shot, so it inherits the same conflict.
    if (options.one_shot or options.capture_raw) and options.file_per_client:
        op.error("--file-per-client records several clients, so it cannot be combined with --one-shot")
    if options.capture_raw:
        if args:
            op.error("OUTPUT is implied by --capture-raw (session.vdo in the archive); do not also pass OUTPUT")
        try:
            check_capture_target(options.capture_raw)
        except ValueError as exc:
            op.error(str(exc))
    elif options.capture_raw_unsafe:
        op.error("--capture-raw-unsafe is only meaningful with --capture-raw")
    elif len(args) != 1:
        op.error("incorrect number of arguments")
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
        op.error("--file-per-client requires OUTPUT to be a directory")
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


def vncdo() -> None:
    from vncdotool import __version__

    usage = "%prog [options] CMD CMDARGS|-|filename"
    description = "Command line control of a VNC server"
    version = "%prog " + __version__

    op = VNCDoToolOptionParser(usage=usage, description=description, version=version)
    add_standard_options(op)

    op.add_option(
        "--delay",
        metavar="MILLISECONDS",
        default=os.environ.get("VNCDOTOOL_DELAY", 10),
        type="int",
        help="delay MILLISECONDS between actions [%defaultms]",
    )
    op.add_option(
        "--force-caps",
        action="store_true",
        help="for non-compliant servers, send shift-LETTER, ensures capitalization works",
    )
    op.add_option(
        "--localcursor",
        action="store_true",
        help="mouse pointer drawn client-side, useful when server does not include cursor",
    )
    op.add_option(
        "--nocursor",
        action="store_true",
        help="no mouse pointer in screen captures",
    )
    op.add_option(
        "--disable-desktop-resizing",
        action="store_true",
        help="disable desktop resizing, this was default behaviour < 0.11",
    )
    op.add_option(
        "-t",
        "--timeout",
        type="float",
        metavar="SECONDS",
        help="abort if unable to complete all actions within TIMEOUT seconds",
    )
    op.add_option(
        "-w",
        "--warp",
        type="float",
        metavar="FACTOR",
        default=1.0,
        help="pause time is accelerated by FACTOR [x%default]",
    )
    op.add_option(
        "-i",
        "--incremental-refreshes",
        action="store_true",
        default=False,
        help='set the "incremental" flag',
    )

    options, args = op.parse_args()
    if not len(args):
        op.error("no command provided")

    setup_logging(options)
    options.address_family, options.host, options.port = parse_server(options.server)

    log.info("connecting to %s:%s", options.host, options.port)

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

    if options.timeout:
        message = "TIMEOUT Exceeded (%ss)" % options.timeout
        failure = Failure(TimeoutError(message))
        reactor.callLater(options.timeout, factory.error, failure)

    reactor.run()

    # the reactor stopping without an outcome is itself a failure
    sys.exit(ExitStatus.ERROR if reactor.exit_status is None else reactor.exit_status)


def vncdo_replay() -> None:
    """Replay a `vnclog --capture-raw` archive: serve it, or drive it.

    Two processes, so anything can take the client side. See docs/capture.rst."""
    from vncdotool import __version__
    from .replay import (
        DEFAULT_BIND,
        DEFAULT_CLIENT_TIMEOUT,
        DEFAULT_PORT,
        DEFAULT_SERVER,
        ReplayFactory,
        load_capture,
    )

    op = VNCDoToolOptionParser(
        usage="%prog [options] CAPTURE.zip [CMD CMDARGS...]",
        description="Replay a vnclog --capture-raw archive. Without --server, runs the "
        "session.vdo recorded inside CAPTURE.zip through vncdo, plus any commands given "
        "after it. See docs/capture.rst.",
        version="%prog " + __version__,
    )
    op.add_option(
        "--server",
        action="store_true",
        default=False,
        help="serve the archive's recorded bytes to whatever client connects, instead of "
        "being the client",
    )
    op.add_option(
        "-s",
        "--connect",
        metavar="ADDRESS",
        default=DEFAULT_SERVER,
        help="client mode: the replay server to drive the session against [%default]",
    )
    op.add_option(
        "--listen",
        type="int",
        metavar="PORT",
        default=DEFAULT_PORT,
        help="--server: TCP port to listen on [%default]",
    )
    op.add_option(
        "--bind",
        metavar="ADDR",
        default=DEFAULT_BIND,
        help="--server: interface to listen on [%default], i.e. local connections only. A "
        "--capture-raw-unsafe archive replays whatever credentials it carried, so opening "
        "this up is a deliberate call to make.",
    )
    op.add_option(
        "--client-timeout",
        type="float",
        metavar="SECONDS",
        default=DEFAULT_CLIENT_TIMEOUT,
        help="--server: warn if the client sends nothing for this long [%default]",
    )
    op.add_option(
        "--forever",
        action="store_true",
        default=False,
        help="--server: keep accepting a new client after each connection ends",
    )
    op.add_option("-v", "--verbose", action="store_true", help="hexdump client->server bytes")

    options, args = op.parse_args()
    if not args:
        op.error("no capture archive given")
    archive, extra = args[0], args[1:]

    logging.basicConfig(
        level=logging.DEBUG if options.verbose else logging.INFO,
        format="vncdo-replay: %(levelname)s: %(message)s",
    )

    try:
        capture = load_capture(archive)
    except ValueError as exc:
        op.error(str(exc))

    if not options.server:
        _replay_client(op, options, capture, archive, extra)
        return

    if extra:
        op.error("--server serves bytes and takes no commands; run those from a client instead")
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
    op: optparse.OptionParser,
    options: optparse.Values,
    capture: object,
    archive: str,
    extra: list[str],
) -> None:
    """Run the archive's recorded session through `vncdo`.

    Recorded events, not hand-typed: another session is not evidence."""
    if not capture.session_vdo.strip() and not extra:
        op.error(
            f"{archive} records no session.vdo (a GUI-driven capture records events, not "
            "vncdo commands), and no commands were given to run instead"
        )

    workdir = tempfile.mkdtemp(prefix="vncdo-replay-")
    try:
        script = os.path.join(workdir, "session.vdo")
        with open(script, "wb") as fh:
            fh.write(capture.session_vdo)
        sys.argv = ["vncdo", "-s", options.connect] + ([script] if capture.session_vdo.strip() else []) + extra
        vncdo()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    vncdo()
