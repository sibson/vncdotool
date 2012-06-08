#!/usr/bin/env python
"""
Command line interface to interact with a VNC Server

(c) 2010 Marc Sibson

MIT License
"""
import optparse
import sys
import time
import traceback
import os


from twisted.internet import reactor, defer
from twisted.python import log
from vncdotool.client import VNCDoToolFactory, VNCDoToolClient
from vncdotool.loggingproxy import VNCLoggingServerFactory


SUPPORTED_FORMATS = ('png', 'jpg', 'jpeg', 'gif', 'bmp')

def log_connected(pcol):
    log.msg('connected to %s' % pcol.name)
    return pcol


def error(reason):
    reason.printTraceback()

    reactor.exit_status = 10
    reactor.stop()


def stop(pcol):
    reactor.exit_status = 0
    pcol.transport.loseConnection()
    # XXX delay
    reactor.callLater(0.1, reactor.stop)


class VNCDoToolOptionParser(optparse.OptionParser):
    def format_help(self, **kwargs):
        result = optparse.OptionParser.format_help(self, **kwargs)
        result += '\n'.join(['',
            'Commands (CMD):',
            '  key KEY:\tsend KEY to server',
            '\t\tKEY is alphanumeric or a keysym, e.g. ctrl-c, del',
            '  type TEXT:\tsend alphanumeric string of TEXT',
            '  move X Y:\tmove the mouse cursor to position X,Y',
            '  click BUTTON:\tsend a mouse BUTTON click',
            '  capture FILE:\tsave current screen as FILE',
            '  expect FILE FUZZ:  Wait until the screen matches FILE',
            '\t\tFUZZ amount of error tolerance (RMSE) in match',
            '  mousedown BUTTON:\tsend BUTTON down',
            '  mouseup BUTTON:\tsend BUTTON up',
            '  pause DURATION:\twait DURATION seconds before sending next',
            '  drag X Y:\tmove the mouse to X,Y in small steps',
            '  proxy PORT:\tlog and forward activity on PORT',
            '',
        ])
        return result


def pause(client, duration):
    d = defer.Deferred()
    reactor.callLater(duration, d.callback, client)
    return d

def build_command_list(factory, args):
    client = VNCDoToolClient

    while args:
        cmd = args.pop(0)
        if cmd == 'key':
            key = args.pop(0)
            factory.deferred.addCallback(client.keyPress, key)
        elif cmd == 'move':
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
        elif cmd == 'pause':
            duration = float(args.pop(0))
            factory.deferred.addCallback(pause, duration)
        elif cmd in 'drag':
            x, y = int(args.pop(0)), int(args.pop(0))
            factory.deferred.addCallback(client.mouseDrag, x, y)
        else:
            print 'unknown cmd "%s"' % cmd


def build_tool(options, args):
    factory = VNCDoToolFactory()
    if options.verbose:
        factory.deferred.addCallbacks(log_connected)

    build_command_list(factory, args)

    factory.deferred.addCallback(stop)
    factory.deferred.addErrback(error)

    reactor.connectTCP(options.host, int(options.port), factory)
    reactor.exit_status = 1

    return factory


def build_proxy(options, port):
    factory = VNCLoggingServerFactory(options.host, int(options.port))
    reactor.listenTCP(port, factory)
    reactor.exit_status = 0

    return factory



def main():
    usage = '%prog [options] CMD CMDARGS'
    description = 'Command line interaction with a VNC server'
    op = VNCDoToolOptionParser(usage=usage, description=description)
    op.disable_interspersed_args()
    op.add_option('-d', '--display', action='store', metavar='DISPLAY',
        type='int', default=0,
        help='connect to vnc server display :DISPLAY [%default]')
    op.add_option('-p', '--password', action='store', metavar='PASSwORD',
        help='use password to access server')
    op.add_option('-s', '--server', action='store', metavar='ADDRESS',
        default='127.0.0.1',
        help='connect to vnc server at ADDRESS[:PORT] [%default]')
    op.add_option('-v', '--verbose', action='store_true')

    options, args = op.parse_args()
    if not len(args):
        op.error('no command provided')

    try:
        options.host, options.port = options.server.split(':')
    except ValueError:
        options.host = options.server
        options.port = options.display + 5900
    options.port = int(options.port)

    if 'proxy' in args:
        args.pop(0)
        port = int(args.pop(0))
        factory = build_proxy(options, port)
    else:
        factory = build_tool(options, args)

    if options.password:
        factory.password = options.password

    if options.verbose:
        log.msg('connecting to %s:%s' % (options.host, options.port))
        factory.logger = log.msg
        log.startLogging(sys.stdout)

    reactor.run()
    sys.exit(reactor.exit_status)


if __name__ == '__main__':
    main()
