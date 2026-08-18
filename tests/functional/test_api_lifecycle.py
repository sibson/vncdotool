"""In-process coverage of ``vncdotool.api``'s *lifecycle* -- context-manager
use, reconnection, error propagation, timeouts, ``shutdown()`` cleanliness.
Server compatibility belongs to the subprocess grid in test_server_compat_docker.py.

``api.connect()`` starts the Twisted reactor in a daemon thread, and a
reactor cannot be restarted once stopped, so one process gets one reactor
for its whole lifetime: this is the only module allowed to call it. A
second in-process module would either race this one for it or leave its
own reactor thread wedged on exit -- new in-process tests belong in
*this* file, sharing *this* reactor.

``setUpModule`` makes the first connection itself, so the reactor is
running before any test method does -- no test depends on being first.
"""

import queue
import socket
import threading
import time
import unittest
from unittest import mock

from twisted.internet import reactor
from twisted.internet.error import ConnectError
from twisted.internet.protocol import Factory, Protocol
from twisted.python import threadable

from vncdotool import api

from .utils import HOST, LIBVNCSERVER_EXAMPLE as LIBVNC, SUBPROCESS_TIMEOUT_HEADROOM, connect, port_open

# Same headroom the subprocess grid adds: the bare 5s server budget was
# observed to flake under load.
HAPPY_TIMEOUT = LIBVNC.timeout + SUBPROCESS_TIMEOUT_HEADROOM

SHORT_TIMEOUT = 2.0

# join() budget for the closed-port helper thread: long enough to fail
# promptly, short enough that a real hang doesn't stall the suite.
HANG_GUARD_TIMEOUT = 10.0

# Bound for a call dispatched onto the reactor thread via callFromThread --
# a local listenTCP/stopListening, not network I/O, so this is generous
# only relative to how fast that actually is.
REACTOR_CALL_TIMEOUT = 2.0


def setUpModule() -> None:
    if not port_open(HOST, LIBVNC.port):
        raise RuntimeError(
            f"libvncserver-example not reachable on {HOST}:{LIBVNC.port} -- "
            "start the servers first with `make servers-up`"
        )
    with connect(LIBVNC, timeout=HAPPY_TIMEOUT) as client:
        client.refreshScreen()


def tearDownModule() -> None:
    # Exactly once per process: without it the interpreter hangs on the
    # non-daemon worker threads Twisted runs under the reactor.
    api.shutdown()


class TestApiLifecycle(unittest.TestCase):
    """Lifecycle cases against the libvncserver-example:5935 container.

    Independent of each other and of run order: the one case that could
    wedge the shared reactor (the closed-port case) is bounded by its own
    timeout and helper thread, not by being run last.
    """

    def test_context_manager_connect(self) -> None:
        """The documented ``with api.connect(...) as client:`` pattern works."""
        with connect(LIBVNC, timeout=HAPPY_TIMEOUT) as client:
            client.keyPress("x")

    def test_sequential_reconnects(self) -> None:
        """``shutdown()`` is what's terminal, not ``disconnect()``: otherwise no
        long-running application could reconnect after a single drop.
        """
        for _ in range(2):
            with connect(LIBVNC, timeout=HAPPY_TIMEOUT) as client:
                client.refreshScreen()

    def test_timeout_raises_timeout_error(self) -> None:
        """``api.connect()`` is fire-and-forget and never raises here; the
        timeout comes from the first call that has to wait on the
        never-completing handshake.
        """
        listener = _SilentListener()
        listener.start()
        self.addCleanup(listener.stop)

        client = api.connect(f"{HOST}::{listener.port}")
        client.timeout = SHORT_TIMEOUT
        self.addCleanup(client.disconnect)

        start = time.monotonic()
        with self.assertRaises(TimeoutError):
            client.refreshScreen()
        elapsed = time.monotonic() - start

        # Tight bound: the timeout path costs mild thread-wakeup slack at
        # most. Padding this further would hide a real regression instead
        # of catching one.
        self.assertLess(elapsed, SHORT_TIMEOUT + 1.0)

    def test_connect_dispatches_onto_reactor_thread(self) -> None:
        """Asserts on thread identity rather than on an outcome: a connect
        dispatched off the reactor thread still succeeds in practice, so
        there is no failure to observe.
        """
        in_io_thread: "queue.Queue[bool]" = queue.Queue()
        real_factory_connect = api.factory_connect

        def spy(*args, **kwargs):
            in_io_thread.put(threadable.isInIOThread())
            return real_factory_connect(*args, **kwargs)

        with mock.patch.object(api, "factory_connect", spy):
            client = api.connect(f"{HOST}::{LIBVNC.port}", password=LIBVNC.password)
            client.timeout = HAPPY_TIMEOUT
            self.addCleanup(client.disconnect)
            self.assertTrue(
                in_io_thread.get(timeout=REACTOR_CALL_TIMEOUT),
                "factory_connect ran outside the reactor thread",
            )

    def test_disconnect_after_command_error_returns_promptly(self) -> None:
        """A failed command must not stop ``disconnect()`` from firing.

        ``disconnect()`` chains onto ``factory.deferred``, which a failed
        ``captureScreen`` leaves in an errored state -- see #146.
        """
        client = connect(LIBVNC, timeout=SHORT_TIMEOUT)

        with self.assertRaises(FileNotFoundError):
            client.captureScreen("no/such/dir/test.png")

        start = time.monotonic()
        client.disconnect()
        elapsed = time.monotonic() - start

        self.assertLess(elapsed, SHORT_TIMEOUT / 2)

    def test_closed_port_raises_promptly(self) -> None:
        """Bounded twice over -- a per-client timeout, and a helper thread
        joined with a deadline -- so even a wedge fails only this test,
        not the suite.

        Twisted's ``ConnectionRefusedError`` is a ``ConnectError``, not the
        stdlib ``OSError`` of the same name, so assert on that base class.
        """
        closed_port = _closed_port()

        outcome: dict = {}

        def attempt() -> None:
            try:
                client = api.connect(f"{HOST}::{closed_port}")
                client.timeout = SHORT_TIMEOUT
                try:
                    client.refreshScreen()
                    outcome["result"] = "no exception"
                except Exception as exc:  # noqa: BLE001 - captured for the assertion below
                    outcome["exception"] = exc
                finally:
                    client.disconnect()
            except Exception as exc:  # noqa: BLE001 - connect() itself is not expected to raise
                outcome["exception"] = exc

        worker = threading.Thread(target=attempt, name="closed-port-attempt", daemon=True)
        worker.start()
        worker.join(timeout=HANG_GUARD_TIMEOUT)

        if worker.is_alive():
            self.fail(
                f"connect()/refreshScreen() against a closed port did not "
                f"return within {HANG_GUARD_TIMEOUT}s -- this would have "
                "hung the process"
            )

        self.assertIn("exception", outcome, f"expected an exception, got: {outcome}")
        # The family, not the exact class: any prompt, clear connection
        # failure satisfies the lifecycle guarantee.
        self.assertIsInstance(outcome["exception"], ConnectError)


class _SilentProtocol(Protocol):
    """Accepts the connection and never sends or reads anything."""


class _SilentListener:
    """A TCP listener on api.connect()'s own reactor that accepts and then
    never speaks, forcing a protocol-level timeout rather than a
    connection-refused. This process gets exactly one reactor, so this
    reuses it rather than starting a second one via raw sockets.
    """

    def start(self) -> None:
        ready: "queue.Queue[None]" = queue.Queue()

        def _listen() -> None:
            self._port = reactor.listenTCP(0, Factory.forProtocol(_SilentProtocol), interface=HOST)
            ready.put(None)

        reactor.callFromThread(_listen)
        ready.get(timeout=REACTOR_CALL_TIMEOUT)
        self.port = self._port.getHost().port

    def stop(self) -> None:
        reactor.callFromThread(self._port.stopListening)


def _closed_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((HOST, 0))
    port = s.getsockname()[1]
    s.close()
    return port


if __name__ == "__main__":
    unittest.main()
