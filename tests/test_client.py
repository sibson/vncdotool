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

    def test_expect_initial_match(self):
        self.client.expect('bar.png')

    def test_expect_blocks_until_match(self):
        pass
        self.client.expect('bar.png')
        # thousands of misses
