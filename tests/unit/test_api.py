import unittest
from unittest import mock

from twisted.internet.defer import Deferred, succeed

from vncdotool import api


class _Protocol:
    def __init__(self) -> None:
        self.pending: list[Deferred] = []

    def slow(self) -> Deferred:
        d: Deferred = Deferred()
        self.pending.append(d)
        return d

    def fast(self) -> str:
        return "fast"


class _Factory:
    protocol = _Protocol

    def __init__(self, protocol: _Protocol) -> None:
        self.deferred = succeed(protocol)


class TestThreadedVNCClientProxy(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(api.reactor, "callFromThread", lambda f, *args, **kwargs: f(*args, **kwargs))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_timed_out_call_does_not_answer_the_next_one(self) -> None:
        protocol = _Protocol()
        client = api.ThreadedVNCClientProxy(_Factory(protocol), timeout=0.01)

        with self.assertRaises(TimeoutError):
            client.slow()
        protocol.pending[0].callback(protocol)

        self.assertEqual(client.fast(), "fast")
