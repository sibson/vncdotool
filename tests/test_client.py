class TestClient(object):
    def setUp(self):
        pass

    def test_keyPress_single(self):
        self.client.keyPress('a')

    def test_keyPress_multiple(self):
        self.client.keyPress('ctrl-alt-del')

    def test_capture(self):
        self.client.capture('foo.png')

    def test_capture_no_pil(self):
        self.client.capture('foo.png')

    def test_multiple_captures(self):
        self.client.capture('foo.png')
        self.client.capture('bar.png')
