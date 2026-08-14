"""In-process coverage of ``vncdotool.api``'s *lifecycle* -- context-manager
use, reconnection, error propagation, timeouts, ``shutdown()`` cleanliness.
Server compatibility belongs to the subprocess grid in test_servers.py.

THIS IS THE ONE MODULE ALLOWED TO CALL api.connect().
-----------------------------------------------------

``api.connect()`` starts the Twisted reactor in a daemon thread, and a
reactor cannot be restarted once stopped, so one process gets one reactor
for its whole lifetime. A second in-process module would either race this
one for it or leave its own reactor thread wedged on exit -- new in-process
tests belong in *this* file, sharing *this* reactor.

Ordering matters for the same reason: every case here shares that reactor,
torn down once by ``tearDownModule``. The one case that could wedge it (the
closed-port case) is ordered last so a hang there poisons nothing before it.
"""

import socket
import threading
import time
import unittest

from twisted.internet.error import ConnectError

from vncdotool import api

from .vncservers import DOCKER_SERVERS, HOST, SUBPROCESS_TIMEOUT_HEADROOM, connect, port_open

TIGERVNC = next(s for s in DOCKER_SERVERS if s.name == "tigervnc")

# Same headroom the subprocess grid adds: the bare 5s server budget was
# observed to flake under load.
HAPPY_TIMEOUT = TIGERVNC.timeout + SUBPROCESS_TIMEOUT_HEADROOM

# Tight budget for the cases that want to observe a timeout quickly.
SHORT_TIMEOUT = 2.0

# join() budget for the closed-port helper thread: long enough to fail
# promptly, short enough that a real hang doesn't stall the suite.
HANG_GUARD_TIMEOUT = 10.0


def setUpModule() -> None:
    if not port_open(HOST, TIGERVNC.port):
        raise unittest.SkipTest(
            f"tigervnc not reachable on {HOST}:{TIGERVNC.port} -- "
            "start the servers first with `make servers-up`"
        )


def tearDownModule() -> None:
    # Exactly once per process: without it the interpreter hangs on the
    # non-daemon worker threads Twisted runs under the reactor.
    api.shutdown()


class TestApiLifecycle(unittest.TestCase):
    """Ordered lifecycle cases against the tigervnc:5931 container.

    Names are prefixed to fix run order: well-behaved cases first, the
    potentially-hanging one last.
    """

    def test_a_connect_op_disconnect(self) -> None:
        """connect -> one trivial op -> disconnect: clean, no exception."""
        client = api.connect(f"{HOST}::{TIGERVNC.port}")
        client.timeout = HAPPY_TIMEOUT
        try:
            client.refreshScreen()
        finally:
            client.disconnect()

    def test_b_context_manager(self) -> None:
        """The documented ``with api.connect(...) as client:`` pattern works."""
        with connect(TIGERVNC, timeout=HAPPY_TIMEOUT) as client:
            client.keyPress("x")

    def test_c_sequential_connects(self) -> None:
        """The reactor survives a disconnect and serves a second connection.

        ``shutdown()`` is what's terminal, not ``disconnect()``: otherwise no
        long-running application could reconnect after a single drop.
        """
        for _ in range(2):
            with connect(TIGERVNC, timeout=HAPPY_TIMEOUT) as client:
                client.refreshScreen()

    def test_d_timeout_raises_timeout_error(self) -> None:
        """A call against a port that never speaks RFB raises TimeoutError
        instead of hanging.

        ``api.connect()`` is fire-and-forget and never raises here; the
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

        # Generous bound: proves the timeout fired, without being a
        # flakiness trap on a loaded CI box.
        self.assertLess(elapsed, SHORT_TIMEOUT + 5.0)

    def test_z_closed_port_raises_promptly(self) -> None:
        """connect() to a port nothing listens on fails fast, not hangs.

        Ordered last (``z`` prefix): a regression here could wedge the
        shared reactor, so it must not run before anything else. Bounded
        twice over -- a per-client timeout, and a helper thread joined with
        a deadline -- so even a wedge fails this test rather than the suite.

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
                "hung the process; see the docstring above for why this "
                "test is ordered last"
            )

        self.assertIn("exception", outcome, f"expected an exception, got: {outcome}")
        # The family, not the exact class: any prompt, clear connection
        # failure satisfies the lifecycle guarantee.
        self.assertIsInstance(outcome["exception"], ConnectError)


class _SilentListener:
    """A TCP listener that accepts and then never speaks, forcing a
    protocol-level timeout rather than a connection-refused.
    """

    def __init__(self) -> None:
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((HOST, 0))
        self.port = self._socket.getsockname()[1]
        self._socket.listen(1)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._stopped = threading.Event()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        self._socket.close()

    def _serve(self) -> None:
        self._socket.settimeout(1.0)
        while not self._stopped.is_set():
            try:
                conn, _ = self._socket.accept()
            except TimeoutError:
                continue  # idle poll; socket.timeout IS an OSError, catch it first
            except OSError:
                return
            # Accept and go silent: read nothing, write nothing, until
            # told to stop.
            while not self._stopped.is_set():
                time.sleep(0.1)
            conn.close()
            return


def _closed_port() -> int:
    """A port nothing listens on, found by binding and releasing it."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((HOST, 0))
    port = s.getsockname()[1]
    s.close()
    return port


if __name__ == "__main__":
    unittest.main()
