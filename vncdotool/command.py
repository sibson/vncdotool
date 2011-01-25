#!/usr/bin/env python
"""
Command line interface to interact with a VNC Server

(c) 2010 Marc Sibson

MIT License
"""
import optparse

from twisted.internet import reactor

from vncdotool.client import VNCDoToolFactory, VNCDoToolClient

def log_connected(pcol):
    print 'connected to', pcol.name
    return pcol


def log_failed(reason):
    print 'connection failed', reason.getErrorMesssage()


def stop(pcol):
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
    
    if opts.verbose:
        f.deferred.addCallbacks(log_connected)
    f.deferred.addErrback(log_failed)

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
            f.deferred.addCallback(VNCDoToolClient.capture, filename)
        else:
            print 'unknown cmd "%s"' % cmd
        
    f.deferred.addCallback(stop)

    reactor.connectTCP(opts.host, opts.port, f)
    reactor.run()

if __name__ == '__main__':
    main()
