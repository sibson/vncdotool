#!/usr/bin/env python
"""
Command line interface to interact with a VNC Server

(c) 2010 Marc Sibson

MIT License
"""
import getpass
import optparse
import sys
import os
import shlex
import logging
import logging.handlers

from twisted.python.log import PythonLoggingObserver
from twisted.internet import reactor, protocol
from twisted.python import log
from twisted.python.failure import Failure

from vncdotool.client import VNCDoToolFactory, VNCDoToolClient
from vncdotool.loggingproxy import VNCLoggingServerFactory

log = logging.getLogger()

SUPPORTED_FORMATS = ('png', 'jpg', 'jpeg', 'gif', 'bmp')


class TimeoutError(RuntimeError):
    pass


def log_exceptions(type_, value, tb):
    log.critical('Unhandled exception:', exc_info=(type_, value, tb))


def log_connected(pcol):
    log.info('connected to %s' % pcol.name)
    return pcol


def error(reason):
    log.critical(reason.getErrorMessage())
    reactor.exit_status = 10
    reactor.callLater(0.1, reactor.stop)


def stop(pcol):
    reactor.exit_status = 0
    pcol.transport.loseConnection()
    # XXX delay
    reactor.callLater(0.1, reactor.stop)


class VNCDoCLIClient(VNCDoToolClient):
    def vncRequestPassword(self):
        if self.factory.password is None:
            self.factory.password = getpass.getpass('VNC password:')

        self.sendPassword(self.factory.password)


class ExitingProcess(protocol.ProcessProtocol):

    def processExited(self, reason):
        reactor.callLater(0.1, reactor.stop)

    def errReceived(self, data):
        print data


class VNCDoToolOptionParser(optparse.OptionParser):
    def format_help(self, **kwargs):
        result = optparse.OptionParser.format_help(self, **kwargs)
        result += '\n'.join(
           ['',
            'Commands (CMD):',
            '  key KEY:\tsend KEY to server',
            '\t\tKEY is alphanumeric or a keysym, e.g. ctrl-c, del',
            '  type TEXT:\tsend alphanumeric string of TEXT',
            '  move|mousemove X Y:\tmove the mouse cursor to position X,Y',
            '  click BUTTON:\tsend a mouse BUTTON click',
            '  capture FILE:\tsave current screen as FILE',
            '  expect FILE FUZZ:  Wait until the screen matches FILE',
            '\t\tFUZZ amount of error tolerance (RMSE) in match',
            '  mousedown BUTTON:\tsend BUTTON down',
            '  mouseup BUTTON:\tsend BUTTON up',
            '  pause DURATION:\twait DURATION seconds before sending next',
            '  drag X Y:\tmove the mouse to X,Y in small steps',
            '',
           ])
        return result


def build_command_list(factory, args, delay=None, warp=1.0):
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
        elif cmd == 'capture':
            filename = args.pop(0)
            imgformat = os.path.splitext(filename)[1][1:]
            if imgformat not in SUPPORTED_FORMATS:
                print 'unsupported image format "%s", choose one of %s' % (
                        imgformat, SUPPORTED_FORMATS)
            else:
                factory.deferred.addCallback(client.captureScreen, filename)
        elif cmd == 'expect':
            filename = args.pop(0)
            rms = int(args.pop(0))
            factory.deferred.addCallback(client.expectScreen, filename, rms)
        elif cmd == 'rcapture':
            filename = args.pop(0)
            x = int(args.pop(0))
            y = int(args.pop(0))
            w = int(args.pop(0))
            h = int(args.pop(0))
            imgformat = os.path.splitext(filename)[1][1:]
            if imgformat not in SUPPORTED_FORMATS:
                print 'unsupported image format "%s", choose one of %s' % (
                        imgformat, SUPPORTED_FORMATS)
            else:
                factory.deferred.addCallback(client.captureRegion, filename, x, y, w, h)
        elif cmd == 'rexpect':
            filename = args.pop(0)
            x = int(args.pop(0))
            y = int(args.pop(0))
            rms = int(args.pop(0))
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
            print 'unknown cmd "%s"' % cmd

        if delay and args:
            factory.deferred.addCallback(client.pause, delay)


def build_tool(options, args):
    factory = VNCDoToolFactory()
    factory.protocol = VNCDoCLIClient

    if options.verbose:
        factory.deferred.addCallbacks(log_connected)

    if args == ['-']:
        lex = shlex.shlex(posix=True)
        lex.whitespace_split = True
        args = list(lex)

    build_command_list(factory, args, options.delay, options.warp)

    factory.deferred.addCallback(stop)
    factory.deferred.addErrback(error)

    reactor.connectTCP(options.host, int(options.port), factory)
    reactor.exit_status = 1

    return factory


def build_proxy(options):
    factory = VNCLoggingServerFactory(options.host, int(options.port))
    port = reactor.listenTCP(options.listen, factory)
    reactor.exit_status = 0
    factory.listen_port = port.getHost().port

    return factory


def add_standard_options(parser):
    parser.disable_interspersed_args()

    parser.add_option('-p', '--password', action='store', metavar='PASSWORD',
        help='use password to access server')

    parser.add_option('-s', '--server', action='store', metavar='SERVER',
        default='127.0.0.1',
        help='connect to VNC server at ADDRESS[:DISPLAY|::PORT] [%default]')

    parser.add_option('--logfile', action='store', metavar='FILE',
        help='output logging information to FILE')

    parser.add_option('-v', '--verbose', action='count',
        help='increase verbosity, use multple times')

    return parser


def setup_logging(options):
    # route Twisted log messages via stdlib logging
    if options.logfile:
        handler = logging.handlers.RotatingFileHandler(options.logfile,
                                      maxBytes=5*1024*1024, backupCount=5)
        logging.getLogger().addHandler(handler)
        sys.excepthook = log_exceptions

    logging.basicConfig()
    if options.verbose > 1:
        logging.getLogger().setLevel(logging.DEBUG)
    elif options.verbose:
        logging.getLogger().setLevel(logging.INFO)

    PythonLoggingObserver().start()


def parse_host(server):
    split = server.split(':')

    if not split[0]:
        host = '127.0.0.1'
    else:
        host = split[0]

    if len(split) == 3:  # ::port
        port = int(split[2])
    elif len(split) == 2:  # :display
        port = int(split[1]) + 5900
    else:
        port = 5900

    return host, port


def vnclog():
    usage = '%prog [options] OUTPUT'
    description = 'Capture user interactions with a VNC Server'

    op = optparse.OptionParser(usage=usage, description=description)
    add_standard_options(op)

    op.add_option('--listen', metavar='PORT', type='int',
        help='listen for client connections on PORT [%default]')
    op.set_defaults(listen=5902)

    op.add_option('--forever', action='store_true',
        help='continually accept new connections')

    op.add_option('--viewer', action='store', metavar='CMD',
        help='launch an interactive client using CMD [%default]')

    options, args = op.parse_args()

    setup_logging(options)

    options.host, options.port = parse_host(options.server)

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
        cmdline = '%s localhost::%s' % (options.viewer, factory.listen_port)
        proc = reactor.spawnProcess(ExitingProcess(),
                                    options.viewer, cmdline.split(),
                                    env=os.environ)

    reactor.run()

    sys.exit(reactor.exit_status)


def vncdo():
    usage = '%prog [options] (CMD CMDARGS|-|filename)'
    description = 'Command line control of a VNC server'

    op = VNCDoToolOptionParser(usage=usage, description=description)
    add_standard_options(op)

    op.add_option('--delay', action='store', metavar='MILLISECONDS',
        default=os.environ.get('VNCDOTOOL_DELAY', 10), type='int',
        help='delay MILLISECONDS between actions [%defaultms]')

    op.add_option('--force-caps', action='store_true',
        help='for non-compliant servers, send shift-LETTER, ensures capitalization works')

    op.add_option('--localcursor', action='store_true',
        help='mouse pointer drawn client-side, useful when server does not include cursor')

    op.add_option('--nocursor', action='store_true',
        help='no mouse pointer in screen captures')

    op.add_option('-t', '--timeout', action='store', type='int', metavar='TIMEOUT',
        help='abort if unable to complete all actions within TIMEOUT seconds')

    op.add_option('-w', '--warp', action='store', type='float',
        metavar='FACTOR', default=1.0,
        help='pause time is accelerated by FACTOR [x%default]')

    options, args = op.parse_args()
    if not len(args):
        op.error('no command provided')

    setup_logging(options)
    options.host, options.port = parse_host(options.server)

    log.info('connecting to %s:%s', options.host, options.port)

    factory = build_tool(options, args)
    factory.password = options.password

    if options.localcursor:
        factory.pseudocursor = True

    if options.nocursor:
        factory.nocursor = True

    if options.force_caps:
        factory.force_caps = True

    if options.timeout:
        message = 'TIMEOUT Exceeded (%ss)' % options.timeout
        failure = Failure(TimeoutError(message))
        reactor.callLater(options.timeout, error, failure)

    reactor.run()

    sys.exit(reactor.exit_status)


if __name__ == '__main__':
    vncdo()
