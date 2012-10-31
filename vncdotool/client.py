"""
Twisted based VNC client protocol and factory

(c) 2010 Marc Sibson

MIT License
"""

import rfb
from twisted.internet.defer import Deferred
from twisted.internet import reactor

import getpass
import math
import operator
import time
import logging

log = logging.getLogger('client')


KEYMAP = {
    'bsp': rfb.KEY_BackSpace,
    'tab': rfb.KEY_Tab,
    'return': rfb.KEY_Return,
    'enter': rfb.KEY_Return,
    'esc': rfb.KEY_Escape,
    'ins': rfb.KEY_Insert,
    'delete': rfb.KEY_Delete,
    'del': rfb.KEY_Delete,
    'home': rfb.KEY_Home,
    'end': rfb.KEY_End,
    'pgup': rfb.KEY_PageUp,
    'pgdn': rfb.KEY_PageDown,
    'left': rfb.KEY_Left,
    'up': rfb.KEY_Up,
    'right': rfb.KEY_Right,
    'down': rfb.KEY_Down,

    'slash': rfb.KEY_BackSlash,
    'bslash': rfb.KEY_BackSlash,
    'fslash': rfb.KEY_ForwardSlash,
    'spacebar': rfb.KEY_SpaceBar,
    'space': rfb.KEY_SpaceBar,
    'sb': rfb.KEY_SpaceBar,

    'f1': rfb.KEY_F1,
    'f2': rfb.KEY_F2,
    'f3': rfb.KEY_F3,
    'f4': rfb.KEY_F4,
    'f5': rfb.KEY_F5,
    'f6': rfb.KEY_F6,
    'f7': rfb.KEY_F7,
    'f8': rfb.KEY_F8,
    'f9': rfb.KEY_F9,
    'f10': rfb.KEY_F10,
    'f11': rfb.KEY_F11,
    'f12': rfb.KEY_F12,
    'f13': rfb.KEY_F13,
    'f14': rfb.KEY_F14,
    'f15': rfb.KEY_F15,
    'f16': rfb.KEY_F16,
    'f17': rfb.KEY_F17,
    'f18': rfb.KEY_F18,
    'f19': rfb.KEY_F19,
    'f20': rfb.KEY_F20,

    'lshift': rfb.KEY_ShiftLeft,
    'shift': rfb.KEY_ShiftLeft,
    'rshift': rfb.KEY_ShiftRight,
    'lctrl': rfb.KEY_ControlLeft,
    'ctrl': rfb.KEY_ControlLeft,
    'rctrl': rfb.KEY_ControlRight,
    'lmeta': rfb.KEY_MetaLeft,
    'meta': rfb.KEY_MetaLeft,
    'rmeta': rfb.KEY_MetaRight,
    'lalt': rfb.KEY_AltLeft,
    'alt': rfb.KEY_AltLeft,
    'ralt': rfb.KEY_AltRight,
    'scrlk': rfb.KEY_Scroll_Lock,
    'sysrq': rfb.KEY_Sys_Req,
    'numlk': rfb.KEY_Num_Lock,
    'caplk': rfb.KEY_Caps_Lock,
    'pause': rfb.KEY_Pause,
    'lsuper': rfb.KEY_Super_L,
    'super': rfb.KEY_Super_L,
    'rsuper': rfb.KEY_Super_R,
    'lhyper': rfb.KEY_Hyper_L,
    'hyper': rfb.KEY_Hyper_L,
    'rhyper': rfb.KEY_Hyper_R,

    'kp0': rfb.KEY_KP_0,
    'kp1': rfb.KEY_KP_1,
    'kp2': rfb.KEY_KP_2,
    'kp3': rfb.KEY_KP_3,
    'kp4': rfb.KEY_KP_4,
    'kp5': rfb.KEY_KP_5,
    'kp6': rfb.KEY_KP_6,
    'kp7': rfb.KEY_KP_7,
    'kp8': rfb.KEY_KP_8,
    'kp9': rfb.KEY_KP_9,
    'kpenter': rfb.KEY_KP_Enter,
}


def ImageFactory():
    """ Wrap importing PIL.Image so vncdotool can be used without
    PIL being installed.  Of course capture and expect won't work
    but at least we can still offer key, type, press and move.
    """
    from PIL import Image
    return Image


class VNCDoToolClient(rfb.RFBClient):
    x = 0
    y = 0
    buttons = 0
    screen = None
    deferred = None

    cursor = None
    cmask = None

    def _decodeKey(self, key):
        if len(key) == 1:
            keys = [key]
        else:
            keys = key.split('-')

        keys = [KEYMAP.get(k) or ord(k) for k in keys]

        return keys

    def pause(self, duration):
        d = Deferred()
        reactor.callLater(duration, d.callback, self)
        return d

    def keyPress(self, key):
        """ Send a key press to the server

            key: string: either [a-z] or a from KEYMAP
        """
        log.debug('keyPress %s', key)
        self.keyDown(key)
        self.keyUp(key)

        return self

    def keyDown(self, key):
        log.debug('keyDown %s', key)
        keys = self._decodeKey(key)
        for k in keys:
            self.keyEvent(k, down=1)

        return self

    def keyUp(self, key):
        log.debug('keyUp %s', key)
        keys = self._decodeKey(key)
        for k in keys:
            self.keyEvent(k, down=0)

        return self

    def mousePress(self, button):
        """ Send a mouse click at the last set position

            button: int: [1-n]

        """
        log.debug('mousePress', button)
        buttons = self.buttons | (1 << (button - 1))
        self.pointerEvent(self.x, self.y, buttonmask=buttons)
        self.pointerEvent(self.x, self.y, buttonmask=self.buttons)

        return self

    def mouseDown(self, button):
        """ Send a mouse button down at the last set position

            button: int: [1-n]

        """
        log.debug('mouseDown', button)
        self.buttons |= 1 << (button - 1)
        self.pointerEvent(self.x, self.y, buttonmask=self.buttons)

        return self

    def mouseUp(self, button):
        """ Send mouse button released at the last set position

            button: int: [1-n]

        """
        log.debug('mouseUp', button)
        self.buttons &= ~(1 << (button - 1))
        self.pointerEvent(self.x, self.y, buttonmask=self.buttons)

        return self

    def captureScreen(self, filename):
        """ Save the current display to filename
        """
        # request screen update
        log.debug('captureScreen', filename)
        self.framebufferUpdateRequest()
        self.deferred = Deferred()
        self.deferred.addCallback(self._captureSave, filename)
        return self.deferred

    def _captureSave(self, data, filename):
        log.debug('captureDone', filename)
        self.screen.save(filename)

        return self

    def expectScreen(self, filename, maxrms=0):
        """ Wait until the display matches a target image

            filename: an image file to read and compare against
            maxrms: the maximum root mean square between histograms of the
                    screen and target image
        """
        log.debug('expectScreen', filename)
        self.framebufferUpdateRequest()
        self.expected = ImageFactory().open(filename).histogram()
        self.deferred = Deferred()
        self.deferred.addCallback(self._expectCompare, maxrms)

        return self.deferred

    def _expectCompare(self, image, maxrms):
        hist = image.histogram()
        if len(hist) == len(self.expected):
            rms = math.sqrt(
                        reduce(operator.add, map(lambda a, b: (a - b) ** 2,
                            hist, self.expected)) / len(hist))

            log.debug('rms', int(rms))
            if rms <= maxrms:
                return self

        self.deferred = Deferred()
        self.deferred.addCallback(self._expectCompare, maxrms)
        self.framebufferUpdateRequest(incremental=1)

        return self.deferred

    def mouseMove(self, x, y):
        """ Move the mouse pointer to position (x, y)
        """
        log.debug('mouseMove', x, y)
        self.x, self.y = x, y
        self.pointerEvent(x, y, self.buttons)
        return self

    def mouseDrag(self, x, y, step=1):
        """ Move the mouse point to position (x, y) in increments of step
        """
        log.debug('mouseDrag', x, y)
        if x < self.x:
            xsteps = [self.x - i for i in xrange(step, self.x - x + 1, step)]
        else:
            xsteps = xrange(self.x, x, step)

        if y < self.y:
            ysteps = [self.y - i for i in xrange(step, self.y - y + 1, step)]
        else:
            ysteps = xrange(self.y, y, step)

        for ypos in ysteps:
            time.sleep(.2)
            self.mouseMove(self.x, ypos)

        for xpos in xsteps:
            time.sleep(.2)
            self.mouseMove(xpos, self.y)

        self.mouseMove(x, y)

        return self

    #
    # base customizations
    #
    def vncConnectionMade(self):
        self.setPixelFormat()
        encodings = [rfb.RAW_ENCODING]
        if self.factory.pseudocusor or self.factory.nocursor:
            encodings.append(rfb.PSEUDO_CURSOR_ENCODING)
        self.setEncodings(encodings)
        self.factory.clientConnectionMade(self)

    def bell(self):
        print 'ding'

    def copy_text(self, text):
        print 'clipboard copy', repr(text)

    def paste(self, message):
        self.clientCutText(message)
        return self

    def updateRectangle(self, x, y, width, height, data):
        # ignore empty updates
        if not data:
            return

        size = (width, height)
        update = ImageFactory().fromstring('RGB', size, data, 'raw', 'RGBX')
        if not self.screen:
            self.screen = update
        # track screen upward screen resizes, often occur during os boot
        elif self.screen.size[0] < width or self.screen.size[1] < height:
            self.screen = update
        else:
            self.screen.paste(update, (x, y))

        self.drawCursor()

    def commitUpdate(self, rectangles):
        if self.deferred:
            d = self.deferred
            self.deferred = None
            d.callback(self.screen)

    def updateCursor(self, x, y, width, height, image, mask):
        if self.factory.nocursor:
            return

        if not width or not height:
            self.cursor = None

        self.cursor = ImageFactory().fromstring('RGBX', (width, height), image)
        self.cmask = ImageFactory().fromstring('1', (width, height), mask)
        self.cfocus = x, y
        self.drawCursor()

    def drawCursor(self):
        if not self.cursor:
            return

        if not self.screen:
            return

        x = self.x - self.cfocus[0]
        y = self.y - self.cfocus[1]
        self.screen.paste(self.cursor, (x, y), self.cmask)

    def vncRequestPassword(self):
        if self.factory.password is None:
            self.factory.password = getpass.getpass()

        self.sendPassword(self.factory.password)


class VNCDoToolFactory(rfb.RFBFactory):
    password = None

    protocol = VNCDoToolClient
    shared = True

    pseudocusor = False
    nocursor = False

    def __init__(self):
        self.deferred = Deferred()

    def clientConnectionFailed(self, connector, reason):
        self.deferred.errback(reason)
        self.deferred = None

    def clientConnectionMade(self, protocol):
        self.deferred.callback(protocol)
        self.deferred = None
