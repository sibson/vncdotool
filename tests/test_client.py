class TestClient(object):
    def setUp(self):
        pass

    def test_keyPress_single(self):
        self.client.keyPress('a')

    def test_keyPress_multiple(self):
        self.client.keyPress('ctrl-alt-del')
