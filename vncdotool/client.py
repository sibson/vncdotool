"""
Twisted based VNC client protocol and factory

(c) 2010 Marc Sibson

MIT License
"""

from . import rfb
from twisted.internet.defer import Deferred
from twisted.internet import reactor

import math
import time
import socket
import logging

log = logging.getLogger('vncdotool.client')


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

# Enable using vncdotool without PIL. Of course capture and expect
# won't work but at least we can still offer key, type, press and
# move.
try:
    from PIL import Image
    # Init PIL to make sure it will not try to import plugin libraries
    # in a thread.
    Image.preinit()
    Image.init()
except ImportError as error:
    # If there is no PIL, raise ImportError where someone tries to use
    # it.
    class _Image(object):
        def __getattr__(self, _):
            raise ImportError(error)
    Image = _Image()


class AuthenticationError(Exception):
    """ VNC Server requires Authentication """


class VNCDoToolClient(rfb.RFBClient):
    encoding = rfb.RAW_ENCODING
    x = 0
    y = 0
    buttons = 0
    screen = None
    image_mode = "RGBX"
    deferred = None

    cursor = None
    cmask = None

    SPECIAL_KEYS_US = "~!@#$%^&*()_+{}|:\"<>?"

    def connectionMade(self):
        rfb.RFBClient.connectionMade(self)

        if self.transport.addressFamily == socket.AF_INET:
            self.transport.setTcpNoDelay(True)

    def _decodeKey(self, key):
        if self.factory.force_caps:
            if key.isupper() or key in self.SPECIAL_KEYS_US:
                key = 'shift-%c' % key

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
        log.debug('mousePress %s', button)
        buttons = self.buttons | (1 << (button - 1))
        self.mouseDown(button)
        self.mouseUp(button)

        return self

    def mouseDown(self, button):
        """ Send a mouse button down at the last set position

            button: int: [1-n]

        """
        log.debug('mouseDown %s', button)
        self.buttons |= 1 << (button - 1)
        self.pointerEvent(self.x, self.y, buttonmask=self.buttons)

        return self

    def mouseUp(self, button):
        """ Send mouse button released at the last set position

            button: int: [1-n]

        """
        log.debug('mouseUp %s', button)
        self.buttons &= ~(1 << (button - 1))
        self.pointerEvent(self.x, self.y, buttonmask=self.buttons)

        return self

    def captureScreen(self, filename):
        """ Save the current display to filename
        """
        log.debug('captureScreen %s', filename)
        return self._capture(filename)

    def captureRegion(self, filename, x, y, w, h):
        """ Save a region of the current display to filename
        """
        log.debug('captureRegion %s', filename)
        return self._capture(filename, x, y, x+w, y+h)

    def refreshScreen(self, incremental=0):
        d = self.deferred = Deferred()
        self.framebufferUpdateRequest(incremental=incremental)
        return d

    def _capture(self, filename, *args):
        d = self.refreshScreen()
        d.addCallback(self._captureSave, filename, *args)
        return d

    def _captureSave(self, data, filename, *args):
        log.debug('captureSave %s', filename)
        if args:
            capture = self.screen.crop(args)
        else:
            capture = self.screen
        capture.save(filename)

        return self

    def expectScreen(self, filename, maxrms=0):
        """ Wait until the display matches a target image

            filename: an image file to read and compare against
            maxrms: the maximum root mean square between histograms of the
                    screen and target image
        """
        log.debug('expectScreen %s', filename)
        return self._expectFramebuffer(filename, 0, 0, maxrms)

    def expectRegion(self, filename, x, y, maxrms=0):
        """ Wait until a portion of the screen matches the target image

            The region compared is defined by the box
            (x, y), (x + image.width, y + image.height)
        """
        log.debug('expectRegion %s (%s, %s)', filename, x, y)
        return self._expectFramebuffer(filename, x, y, maxrms)

    def _expectFramebuffer(self, filename, x, y, maxrms):
        self.framebufferUpdateRequest(incremental=1)
        image = Image.open(filename)
        w, h = image.size
        self.expected = image.histogram()
        self.deferred = Deferred()
        self.deferred.addCallback(self._expectCompare, (x, y, x + w, y + h), maxrms)

        return self.deferred

    def _expectCompare(self, data, box, maxrms):
        image = self.screen.crop(box)

        hist = image.histogram()
        if len(hist) == len(self.expected):
            sum_ = 0
            for h, e in zip(hist, self.expected):
                sum_ += (h - e) ** 2
            rms = math.sqrt(sum_ / len(hist))

            log.debug('rms:%s maxrms: %s', int(rms), int(maxrms))
            if rms <= maxrms:
                return self

        self.deferred = Deferred()
        self.deferred.addCallback(self._expectCompare, box, maxrms)
        self.framebufferUpdateRequest(incremental=1)  # use box ~(x, y, w - x, h - y)?

        return self.deferred

    def mouseMove(self, x, y):
        """ Move the mouse pointer to position (x, y)
        """
        log.debug('mouseMove %d,%d', x, y)
        self.x, self.y = x, y
        self.pointerEvent(x, y, self.buttons)
        return self

    def mouseDrag(self, x, y, step=1):
        """ Move the mouse point to position (x, y) in increments of step
        """
        log.debug('mouseDrag %d,%d', x, y)
        if x < self.x:
            xsteps = [self.x - i for i in range(step, self.x - x + 1, step)]
        else:
            xsteps = range(self.x, x, step)

        if y < self.y:
            ysteps = [self.y - i for i in range(step, self.y - y + 1, step)]
        else:
            ysteps = range(self.y, y, step)

        for ypos in ysteps:
            time.sleep(.2)
            self.mouseMove(self.x, ypos)

        for xpos in xsteps:
            time.sleep(.2)
            self.mouseMove(xpos, self.y)

        self.mouseMove(x, y)

        return self

    def setImageMode(self):
        """ Extracts color ordering and 24 vs. 32 bpp info out of the pixel format information
        """
        if self._version_server == 3.889:
            self.setPixelFormat(
                    bpp = 16, depth = 16, bigendian = 0, truecolor = 1,
                    redmax = 31, greenmax = 63, bluemax = 31,
                    redshift = 11, greenshift = 5, blueshift = 0
                    )
            self.image_mode = "BGR;16"
        elif (self.truecolor and (not self.bigendian) and self.depth == 24
                and self.redmax == 255 and self.greenmax == 255 and self.bluemax == 255):

            pixel = ["X"] * self.bypp
            offsets = [offset // 8 for offset in (self.redshift, self.greenshift, self.blueshift)]
            for offset, color in zip(offsets, "RGB"):
                pixel[offset] = color
            self.image_mode = "".join(pixel)
        else:
            self.setPixelFormat()

    #
    # base customizations
    #
    def vncRequestPassword(self):
        if self.factory.password is None:
            self.transport.loseConnection()
            self.factory.clientConnectionFailed(self, AuthenticationError('password required, but none provided'))
            return
        self.sendPassword(self.factory.password)

    def vncConnectionMade(self):
        self.setImageMode()
        encodings = [self.encoding]
        if self.factory.pseudocursor or self.factory.nocursor:
            encodings.append(rfb.PSEUDO_CURSOR_ENCODING)
        if self.factory.pseudodesktop:
            encodings.append(rfb.PSEUDO_DESKTOP_SIZE_ENCODING)
        self.setEncodings(encodings)
        self.factory.clientConnectionMade(self)

    def bell(self):
        print('ding')

    def copy_text(self, text):
        print('clipboard copy', repr(text))

    def paste(self, message):
        self.clientCutText(message)
        return self

    def updateRectangle(self, x, y, width, height, data):
        # ignore empty updates
        if not data:
            return

        size = (width, height)
        update = Image.frombytes('RGB', size, data, 'raw', self.image_mode)
        if not self.screen:
            self.screen = update
        # track upward screen resizes, often occurs during os boot of VMs
        # When the screen is sent in chunks (as observed on VMWare ESXi), the canvas
        # needs to be resized to fit all existing contents and the update.
        elif self.screen.size[0] < (x+width) or self.screen.size[1] < (y+height):
            new_size = (max(x+width, self.screen.size[0]), max(y+height, self.screen.size[1]))
            new_screen = Image.new("RGB", new_size, "black")
            new_screen.paste(self.screen, (0, 0))
            new_screen.paste(update, (x, y))
            self.screen = new_screen
        else:
            self.screen.paste(update, (x, y))

        self.drawCursor()

    def commitUpdate(self, rectangles):
        if self.deferred:
            d = self.deferred
            self.deferred = None
            d.callback(self)

    def updateCursor(self, x, y, width, height, image, mask):
        if self.factory.nocursor:
            return

        if not width or not height:
            self.cursor = None

        self.cursor = Image.frombytes('RGBX', (width, height), image)
        self.cmask = Image.frombytes('1', (width, height), mask)
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

    def updateDesktopSize(self, width, height):
        new_screen = Image.new("RGB", (width, height), "black")
        if self.screen:
            new_screen.paste(self.screen, (0, 0))
        self.screen = new_screen


class VMWareClient(VNCDoToolClient):
    def dataReceived(self, data):
        single_pixel_update = b'\x00\x01\x00\x00\x00\x00\x00\x01\x00\x01\x00\x00\x00\x00'
        if len(data) == 20 and int(data[0]) == 0 and data[2:16] == single_pixel_update:
            self.framebufferUpdateRequest()
            self._handler()
        else:
            super(VMWareClient, self).dataReceived(data)


class VNCDoToolFactory(rfb.RFBFactory):
    password = None

    protocol = VNCDoToolClient
    shared = True

    pseudocursor = False
    nocursor = False
    pseudodesktop = True
    force_caps = False

    def __init__(self):
        self.deferred = Deferred()

    def clientConnectionLost(self, connector, reason):
        pass

    def clientConnectionFailed(self, connector, reason):
        self.deferred.errback(reason)

    def clientConnectionMade(self, protocol):
        self.deferred.callback(protocol)


class VMWareFactory(VNCDoToolFactory):
    protocol = VMWareClient


def factory_connect(factory, host, port, family):
    if family == socket.AF_INET:
        reactor.connectTCP(host, port, factory)
    elif family == socket.AF_UNIX:
        reactor.connectUNIX(host, factory)
