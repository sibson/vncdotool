class PExpectAssertMixin(object):

    def assertKeyDown(self, key):
        down = u'^.*down:\s+\(%s\)\r' % hex(key)
        self.server.expect(down)

    def assertKeyUp(self, key):
        up = u'^.*up:\s+\(%s\)\r' % hex(key)
        self.server.expect(up)

    def assertMouse(self, x, y, buttonmask):
        output = u'^.*Ptr: mouse button mask %s at %d,%d' % (hex(buttonmask), x, y)
        self.server.expect(output)

    def assertDisconnect(self):
        disco = u'Client 127.0.0.1 gone'
        self.server.expect(disco)
