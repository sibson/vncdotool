#!/usr/bin/env python
"""
Command line interface to interact with a VNC Server

(c) 2010 Marc Sibson

MIT License
"""
import optparse

from twisted.internet import reactor
from twisted.python import log
from vncdotool.client import VNCDoToolFactory, VNCDoToolClient
import sys


def log_connected(pcol):
    log.msg('connected to %s' % pcol.name)
    return pcol


def error(reason):
    try:
        reason = reason.getErrorMessage()
    except AttributeError:
        pass

    print reason
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
            '',
        ])
        return result


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
        elif cmd == 'type':
            for key in args.pop(0):
                factory.deferred.addCallback(client.keyPress, key)
        elif cmd == 'capture':
            filename = args.pop(0)
            factory.deferred.addCallback(client.captureScreen, filename)
        elif cmd == 'expect':
            filename = args.pop(0)
            rms = int(args.pop(0))
            factory.deferred.addCallback(client.expectScreen, filename, rms)
        else:
            print 'unknown cmd "%s"' % cmd


def main():
    usage = '%prog [options] CMD CMDARGS'
    description = 'Command line interaction with a VNC server'
    op = VNCDoToolOptionParser(usage=usage, description=description)
    op.add_option('-d', '--display', action='store', metavar='DISPLAY',
        type='int', default=0,
        help='connect to vnc server display :DISPLAY [%default]')
    op.add_option('-p', '--password', action='store', metavar='PASSwORD',
        help='use password to access server')
    op.add_option('-s', '--server', action='store', metavar='ADDRESS',
        default='127.0.0.1',
        help='connect to vnc server at ADDRESS[:PORT] [%default]')
    op.add_option('-v', '--verbose', action='store_true')

    opts, args = op.parse_args()
    if not len(args):
        op.error('no command provided')

    factory = VNCDoToolFactory()
    try:
        host, port = opts.server.split(':')
    except ValueError:
        host = opts.server
        port = opts.display + 5900

    if opts.password:
        factory.password = opts.password

    if opts.verbose:
        log.msg('connecting to %s:%s' % (host, port))
        factory.logger = log.msg
        log.startLogging(sys.stdout)

    if opts.verbose:
        factory.deferred.addCallbacks(log_connected)

    build_command_list(factory, args)

    factory.deferred.addCallback(stop)
    factory.deferred.addErrback(error)

    reactor.connectTCP(host, int(port), factory)
    reactor.exit_status = 1

    reactor.run()

    sys.exit(reactor.exit_status)

if __name__ == '__main__':
    main()
