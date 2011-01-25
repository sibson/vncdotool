#!/usr/bin/env python
"""
Command line interface to interact with a VNC Server

(c) 2010 Marc Sibson

MIT License
"""
import optparse

from twisted.internet import reactor

from vncdotool.client import VNCDoToolFactory, VNCDoToolClient
import sys

def logger(fmt, *args):
    print fmt % args

def log_connected(pcol):
    print 'connected to', pcol.name
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

def main():
    op = optparse.OptionParser(usage='%prog [options] cmd', 
                                add_help_option=False)
    op.add_option('-d', '--display', action='store', metavar='DISPLAY',
        type='int', default=0,
        help='connect to vnc server on DISPLAY [%default]')
    op.add_option('--help', action='help', 
        help='show this help message')
    op.add_option('-h', '--host', action='store', metavar='HOST',
        default='127.0.0.1',
        help='connect to vnc server at HOST [%default]')
    op.add_option('-p', '--port', action='store', metavar='PORT',
        type='int',
        help='connect to vnc server on PORT')
    op.add_option('-v', '--verbose', action='store_true')

    opts, args = op.parse_args()
    if opts.port is None:
        opts.port = opts.display + 5900
        
    if not len(args):
        op.error('no command provided')

    f = VNCDoToolFactory()
    if opts.verbose:
        print 'connecting to %s:%d' % (opts.host, opts.port)
        f.logger = logger
    
    if opts.verbose:
        f.deferred.addCallbacks(log_connected)

    while args:
        cmd = args.pop(0)
        if cmd == 'key':
            key = args.pop(0)
            f.deferred.addCallback(VNCDoToolClient.keyPress, key)
        elif cmd == 'move':
            x, y = int(args.pop(0)), int(args.pop(0))
            f.deferred.addCallback(VNCDoToolClient.mouseMove, x, y)
        elif cmd == 'click':
            button = int(args.pop(0))
            f.deferred.addCallback(VNCDoToolClient.mousePress, button)
        elif cmd == 'type':
            for key in args.pop(0):
                f.deferred.addCallback(VNCDoToolClient.keyPress, key)
        elif cmd == 'capture':
            filename = args.pop(0)
            f.deferred.addCallback(VNCDoToolClient.captureScreen, filename)
        elif cmd == 'expect':
            filename = args.pop(0)
            rms = int(args.pop(0))
            f.deferred.addCallback(VNCDoToolClient.expectScreen, filename, rms)
        else:
            print 'unknown cmd "%s"' % cmd
        
    f.deferred.addCallback(stop)
    f.deferred.addErrback(error)

    d = reactor.connectTCP(opts.host, opts.port, f)

    reactor.exit_status = 1

    reactor.run()

    sys.exit(reactor.exit_status)

if __name__ == '__main__':
    main()
