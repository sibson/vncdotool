"""The ws:// and wss:// transport, without a reactor or a server.

The live half is tests/functional/test_websocket.py, against the fleet.
"""
import unittest
from unittest import mock

from vncdotool import client, websocket


class TestParseUrl(unittest.TestCase):

    def test_path_and_query_survive(self) -> None:
        url, port = websocket.parse_url("ws://localhost:4444/vnc/c2ec57a?password=selenoid")
        assert url == "ws://localhost:4444/vnc/c2ec57a?password=selenoid"
        assert port == 4444

    def test_empty_path_becomes_root(self) -> None:
        url, port = websocket.parse_url("ws://localhost:5942")
        assert url == "ws://localhost:5942/"

    def test_default_ports(self) -> None:
        assert websocket.parse_url("ws://h/x")[1] == 80
        assert websocket.parse_url("wss://h/x")[1] == 443

    def test_scheme_is_case_insensitive(self) -> None:
        url, _ = websocket.parse_url("WS://Localhost:5942/Path")
        assert url == "ws://localhost:5942/Path"

    def test_fragment_is_dropped(self) -> None:
        url, _ = websocket.parse_url("ws://h:1/p?q=1#frag")
        assert url == "ws://h:1/p?q=1"

    def test_hostless_url_rejected(self) -> None:
        with self.assertRaises(ValueError):
            websocket.parse_url("ws:///vnc")

    def test_other_scheme_rejected(self) -> None:
        with self.assertRaises(ValueError):
            websocket.parse_url("http://h/vnc")


class TestIsWebsocketUrl(unittest.TestCase):

    def test_schemes(self) -> None:
        assert websocket.is_websocket_url("ws://h/x")
        assert websocket.is_websocket_url("WSS://h/x")
        assert not websocket.is_websocket_url("http://h/x")
        assert not websocket.is_websocket_url("127.0.0.1::5900")
        assert not websocket.is_websocket_url("/run/vnc.sock")


class TestRedact(unittest.TestCase):

    def test_query_is_replaced(self) -> None:
        assert websocket.redact("ws://h:1/vnc/s?password=x") == "ws://h:1/vnc/s?<redacted>"

    def test_url_without_query_is_unchanged(self) -> None:
        assert websocket.redact("ws://h:1/vnc/s") == "ws://h:1/vnc/s"

    def test_plain_address_is_unchanged(self) -> None:
        assert websocket.redact("10.11.12.13") == "10.11.12.13"


@mock.patch.object(websocket, "wrapClientTLS")
@mock.patch.object(websocket, "HostnameEndpoint")
class TestConnect(unittest.TestCase):
    """No reactor is started: both endpoint constructors are stand-ins."""

    def setUp(self) -> None:
        patch = mock.patch.object(
            websocket, "_wrapping_factory_class", return_value=mock.Mock()
        )
        self.wrapping_factory = patch.start()
        self.addCleanup(patch.stop)

    def test_ws_connects_without_tls(self, endpoint, wrap_tls) -> None:
        websocket.connect(mock.Mock(), mock.Mock(), "ws://host:5942/vnc/s?token=1")

        endpoint.assert_called_once_with(mock.ANY, "host", 5942)
        wrap_tls.assert_not_called()
        endpoint.return_value.connect.assert_called_once()

    def test_wss_verifies_the_certificate_against_the_hostname(self, endpoint, wrap_tls) -> None:
        with mock.patch.object(websocket, "optionsForClientTLS") as options:
            websocket.connect(mock.Mock(), mock.Mock(), "wss://host:5943/vnc/s")

        options.assert_called_once_with("host")
        wrap_tls.assert_called_once_with(options.return_value, endpoint.return_value)
        wrap_tls.return_value.connect.assert_called_once()

    def test_url_reaches_the_websocket_factory(self, endpoint, wrap_tls) -> None:
        factory = mock.Mock()
        websocket.connect(mock.Mock(), factory, "ws://host:5942/vnc/s?token=1")

        wrapping = self.wrapping_factory.return_value
        assert wrapping.call_args.args == (factory, "ws://host:5942/vnc/s?token=1")


class TestHttpOrigin(unittest.TestCase):

    def test_ws_becomes_http(self) -> None:
        assert websocket.http_origin("ws://h:5942/vnc/s?q=1") == "http://h:5942"

    def test_wss_becomes_https(self) -> None:
        assert websocket.http_origin("wss://h:5943/vnc/s") == "https://h:5943"


class TestHandshakeOffer(unittest.TestCase):
    """Selenoid rejects two subprotocols, and rejects a missing Origin."""

    def setUp(self) -> None:
        self.factory_class = websocket._wrapping_factory_class()

    def build(self, url: str):
        return self.factory_class(
            mock.Mock(), url, reactor=mock.Mock(), enableCompression=False
        )

    def test_only_binary_is_offered(self) -> None:
        assert self.build("ws://h:5942/vnc/s").protocols == ["binary"]

    def test_origin_is_sent(self) -> None:
        assert self.build("ws://h:5942/vnc/s?password=x").origin == "http://h:5942"

    def test_wss_origin_is_https(self) -> None:
        assert self.build("wss://h:5943/vnc/s").origin == "https://h:5943"


class TestFactoryConnectDispatch(unittest.TestCase):

    @mock.patch.object(websocket, "connect")
    def test_websocket_family_hands_over_the_whole_url(self, connect) -> None:
        factory = mock.Mock()
        url = "ws://host:5942/vnc/s?password=x"

        client.factory_connect(factory, url, 5942, websocket.WEBSOCKET)

        assert connect.call_args.args[1:] == (factory, url)
