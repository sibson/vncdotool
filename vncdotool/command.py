#!/usr/bin/env python
"""
Command line interface to interact with a VNC Server

(c) 2010 Marc Sibson

MIT License
"""

import getpass
import ipaddress
import logging
import logging.handlers
import optparse
import os
import shlex
import socket
import sys
from types import TracebackType
from typing import List, Optional, Tuple, Type

from twisted.internet import protocol, reactor
from twisted.internet.error import ConnectionDone
from twisted.internet.interfaces import IConnector
from twisted.python.failure import Failure
from twisted.python.log import PythonLoggingObserver

from .client import TClient, VNCDoToolClient, VNCDoToolFactory, factory_connect
from .loggingproxy import VNCLoggingServerFactory

log = logging.getLogger()

SUPPORTED_FORMATS = ('png', 'jpg', 'jpeg', 'gif', 'bmp')


class TimeoutError(RuntimeError):
    pass


def log_exceptions(type_: Type[BaseException], value: BaseException, tb: Optional[TracebackType]) -> None:
    log.critical('Unhandled exception:', exc_info=(type_, value, tb))


def log_connected(pcol: TClient) -> TClient:
    log.info('connected to %s', pcol.name)
    return pcol


class VNCDoCLIClient(VNCDoToolClient):
    def vncRequestPassword(self) -> None:
        if self.factory.password is None:
            self.factory.password = getpass.getpass('VNC password:')

        self.sendPassword(self.factory.password)


class VNCDoCLIFactory(VNCDoToolFactory):
    protocol = VNCDoCLIClient

    def clientConnectionLost(self, connector: IConnector, reason: Failure) -> None:
        if reason.type == ConnectionDone:
            self.done(0)
        else:
            self.error(reason)

    def clientConnectionFailed(self, connector: IConnector, reason: Failure) -> None:
        self.error(reason)

    def error(self, reason: Failure) -> None:
        log.critical(reason.getErrorMessage())
        self.done(10)

    def done(self, exit_code: int) -> None:
        reactor.exit_status = exit_code
        reactor.callLater(0.1, reactor.stop)


class ExitingProcess(protocol.ProcessProtocol):  # type: ignore[misc]

    def processExited(self, reason: Failure) -> None:
        reactor.callLater(0.1, reactor.stop)

    def errReceived(self, data: bytes) -> None:
        print(data)


class VNCDoToolOptionParser(optparse.OptionParser):
    def format_help(self, formatter: Optional[optparse.HelpFormatter] = None) -> str:
        result = super().format_help(formatter)
        result += (
            '\n'
            'Common Commands (CMD):\n'
            '  key KEY\t\tsend KEY to server, alphanumeric or keysym: ctrl-c, del\n'
            '  type TEXT\t\tsend alphanumeric string of TEXT\n'
            '  typefile FILENAME\t\ttype out the contents of FILENAME\n'
            '  move X Y\t\tmove the mouse cursor to position X,Y\n'
            '  click BUTTON\t\tsend a mouse BUTTON click\n'
            '  capture FILE\t\tsave current screen as FILE\n'
            '  expect FILE FUZZ\twait until screen matches FILE\n'
            '  pause SECONDS\t\twait SECONDS before sending next command\n'
            '\n'
            'Other Commands (CMD):\n'
            '  keyup KEY\t\tsend KEY released\n'
            '  keydown KEY\t\tsend KEY pressed\n'
            '  mousedown BUTTON\tsend BUTTON down\n'
            '  mousemove X Y\t\talias for move\n'
            '  mouseup BUTTON\tsend BUTTON up\n'
            '  drag X Y\t\tmove the mouse to X,Y in small steps\n'
            '  rcapture FILE X Y W H\tcapture a region of the screen\n'
            '  rexpect FILE X Y FUZZ\texpect that matches a region of the screen\n'
            '\n'
            'If a filename is given commands will be read from it, or stdin `-`\n'
        )
        return result


class CommandParseError(RuntimeError):
    pass


def build_command_list(
    factory: VNCDoCLIFactory,
    args: List[str],
    delay: Optional[float] = None,
    warp: float = 1.0,
    incremental_refreshes: bool = False,
) -> None:
    client = VNCDoCLIClient

    if delay:
        delay = float(delay) / 1000.0

    while args:
        cmd = args.pop(0)
        if cmd == 'key':
            key = args.pop(0)
            factory.deferred.addCallback(client.keyPress, key)
        elif cmd in ('kdown', 'keydown'):
            key = args.pop(0)
            factory.deferred.addCallback(client.keyDown, key)
        elif cmd in ('kup', 'keyup'):
            key = args.pop(0)
            factory.deferred.addCallback(client.keyUp, key)
        elif cmd in ('move', 'mousemove'):
            x, y = int(args.pop(0)), int(args.pop(0))
            factory.deferred.addCallback(client.mouseMove, x, y)
        elif cmd == 'click':
            button = int(args.pop(0))
            factory.deferred.addCallback(client.mousePress, button)
        elif cmd in ('mdown', 'mousedown'):
            button = int(args.pop(0))
            factory.deferred.addCallback(client.mouseDown, button)
        elif cmd in ('mup', 'mouseup'):
            button = int(args.pop(0))
            factory.deferred.addCallback(client.mouseUp, button)
        elif cmd == 'type':
            for key in args.pop(0):
                factory.deferred.addCallback(client.keyPress, key)
                if delay:
                    factory.deferred.addCallback(client.pause, delay)
        elif cmd == 'typefile':
            with open(args.pop(0)) as f:
                content = f.read()
                for key in content:
                    if key == '\r':
                        continue
                    if key == '\n':
                        key = 'enter'
                    if key == '\t':
                        key = 'tab'
                    factory.deferred.addCallback(client.keyPress, key)
                    if delay:
                        factory.deferred.addCallback(client.pause, delay)
        elif cmd == 'pastefile':
            with open(args.pop(0)) as f:
                content = f.read().replace('\r\n', '\n')
                factory.deferred.addCallback(client.paste, content)
        elif cmd == 'capture':
            filename = args.pop(0)
            imgformat = os.path.splitext(filename)[1][1:]
            if imgformat not in SUPPORTED_FORMATS:
                raise CommandParseError(f'unsupported image format "{imgformat}", choose one of {SUPPORTED_FORMATS}')
            factory.deferred.addCallback(client.captureScreen, filename, int(incremental_refreshes))
        elif cmd == 'expect':
            filename = args.pop(0)
            rms = float(args.pop(0))
            factory.deferred.addCallback(client.expectScreen, filename, rms)
        elif cmd == 'rcapture':
            filename = args.pop(0)
            x = int(args.pop(0))
            y = int(args.pop(0))
            w = int(args.pop(0))
            h = int(args.pop(0))
            imgformat = os.path.splitext(filename)[1][1:]
            if imgformat not in SUPPORTED_FORMATS:
                raise CommandParseError(f'unsupported image format "{imgformat}", choose one of {SUPPORTED_FORMATS}')
            factory.deferred.addCallback(client.captureRegion, filename, x, y, w, h)
        elif cmd == 'rexpect':
            filename = args.pop(0)
            x = int(args.pop(0))
            y = int(args.pop(0))
            rms = float(args.pop(0))
            factory.deferred.addCallback(client.expectRegion, filename, x, y, rms)
        elif cmd in ('pause', 'sleep'):
            duration = float(args.pop(0)) / warp
            factory.deferred.addCallback(client.pause, duration)
        elif cmd in 'drag':
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


def build_tool(options: optparse.Values, args: List[str]) -> VNCDoCLIFactory:
    factory = VNCDoCLIFactory()

    if options.verbose:
        factory.deferred.addCallbacks(log_connected)

    if args == ['-']:
        lex = shlex.shlex(posix=True)
        lex.whitespace_split = True
        args = list(lex)

    try:
        build_command_list(factory, args, options.delay, options.warp, options.incremental_refreshes)
    except CommandParseError as exc:
        sys.exit(exc)

    factory_connect(factory, options.host, options.port, options.address_family)
    reactor.exit_status = 1

    # close the connection when we're done
    factory.deferred.addCallback(lambda client: client.transport.loseConnection())

    return factory


def build_proxy(options: optparse.Values) -> VNCLoggingServerFactory:
    factory = VNCLoggingServerFactory(options.host, int(options.port))
    factory.password_required = options.password_required
    port = reactor.listenTCP(options.listen, factory)
    reactor.exit_status = 0
    factory.listen_port = port.getHost().port

    return factory


def add_standard_options(parser: optparse.OptionParser) -> optparse.OptionParser:
    parser.disable_interspersed_args()

    parser.add_option(
        '-p',
        '--password',
        help='use password to access server',
    )
    parser.add_option(
        '-u',
        '--username',
        help='use username to access server',
    )
    parser.add_option(
        '-s',
        '--server',
        default='127.0.0.1',
        help='connect to VNC server at ADDRESS[:DISPLAY|::PORT] [%default]',
    )
    parser.add_option(
        '--logfile',
        metavar='FILE',
        help='output logging information to FILE',
    )
    parser.add_option(
        '-v',
        '--verbose',
        action='count',
        default=0,
        help='increase verbosity, use multiple times',
    )
    return parser


def setup_logging(options: optparse.Values) -> None:
    # route Twisted log messages via stdlib logging
    if options.logfile:
        handler = logging.handlers.RotatingFileHandler(
            options.logfile,
            maxBytes=5 << 20,
            backupCount=5
        )
        logging.getLogger().addHandler(handler)
        sys.excepthook = log_exceptions

    logging.basicConfig()
    if options.verbose > 1:
        logging.getLogger().setLevel(logging.DEBUG)
    elif options.verbose:
        logging.getLogger().setLevel(logging.INFO)

    PythonLoggingObserver().start()


def parse_server(server: str) -> Tuple[socket.AddressFamily, str, int]:
    if server.startswith("["):
        host, sep, server = server[1:].partition("]")
        if not sep:
            raise ValueError(server)
        ipaddress.IPv6Address(host)
        split = server.split(':')
        address_family = socket.AF_INET6
    else:
        split = server.split(':')
        if not split[0]:
            host = '127.0.0.1'
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

    usage = '%prog [options] OUTPUT'
    description = 'Capture user interactions with a VNC Server'
    version = "%prog " + __version__

    op = optparse.OptionParser(usage=usage, description=description, version=version)
    add_standard_options(op)
    op.add_option(
        '--listen',
        metavar='PORT',
        default=5902,
        type='int',
        help='listen for client connections on PORT [%default]',
    )
    op.add_option(
        '--forever',
        action='store_true',
        help='continually accept new connections',
    )
    op.add_option(
        '--viewer',
        metavar='CMD',
        help='launch an interactive client using CMD [%default]',
    )
    # ideally we wouldn't need this, VNCLoggingClient should sniff and set this properly
    op.add_option(
        '--password-required',
        action='store_true',
        default=False,
        help='a VNC password is required to connect to the server',
    )
    options, args = op.parse_args()

    setup_logging(options)

    options.address_family, options.host, options.port = parse_server(
        options.server)

    if len(args) != 1:
        op.error('incorrect number of arguments')
    output = args[0]

    factory = build_proxy(options)

    if options.forever and os.path.isdir(output):
        factory.output = output
    elif options.forever:
        op.error('--forever requires OUTPUT to be a directory')
    elif output == '-':
        factory.output = sys.stdout
    else:
        factory.output = open(output, 'w')

    if options.listen == 0:
        log.info('accepting connections on ::%d', factory.listen_port)

    factory.password = options.password

    if options.viewer:
        cmdline = f'{options.viewer} localhost::{factory.listen_port}'
        reactor.spawnProcess(
            ExitingProcess(),
            options.viewer,
            cmdline.split(),
            env=os.environ,
        )
    reactor.run()
    sys.exit(reactor.exit_status)


def vncdo() -> None:
    from vncdotool import __version__

    usage = '%prog [options] CMD CMDARGS|-|filename'
    description = 'Command line control of a VNC server'
    version = "%prog " + __version__

    op = VNCDoToolOptionParser(usage=usage, description=description, version=version)
    add_standard_options(op)

    op.add_option(
        '--delay',
        metavar='MILLISECONDS',
        default=os.environ.get('VNCDOTOOL_DELAY', 10),
        type='int',
        help='delay MILLISECONDS between actions [%defaultms]',
    )
    op.add_option(
        '--force-caps',
        action='store_true',
        help='for non-compliant servers, send shift-LETTER, ensures capitalization works',
    )
    op.add_option(
        '--localcursor',
        action='store_true',
        help='mouse pointer drawn client-side, useful when server does not include cursor',
    )
    op.add_option(
        '--nocursor',
        action='store_true',
        help='no mouse pointer in screen captures',
    )
    op.add_option(
        '--disable-desktop-resizing',
        action='store_true',
        help='disable desktop resizing, this was default behaviour < 0.11',
    )
    op.add_option(
        '-t',
        '--timeout',
        type='float',
        metavar='SECONDS',
        help='abort if unable to complete all actions within TIMEOUT seconds',
    )
    op.add_option(
        '-w',
        '--warp',
        type='float',
        metavar='FACTOR',
        default=1.0,
        help='pause time is accelerated by FACTOR [x%default]',
    )
    op.add_option(
        '-i',
        '--incremental-refreshes',
        action='store_true',
        default=False,
        help='set the "incremental" flag',
    )

    options, args = op.parse_args()
    if not len(args):
        op.error('no command provided')

    setup_logging(options)
    options.address_family, options.host, options.port = parse_server(
        options.server)

    log.info('connecting to %s:%s', options.host, options.port)

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
        message = 'TIMEOUT Exceeded (%ss)' % options.timeout
        failure = Failure(TimeoutError(message))
        reactor.callLater(options.timeout, factory.error, failure)

    reactor.run()

    sys.exit(reactor.exit_status)


if __name__ == '__main__':
    vncdo()
