""" Helpers to allow vncdotool to be intergrated into other applications.

This feature is under development, your help testing and
debugging is appreciated.
"""

import logging
import queue
import socket
import sys
import threading
from types import TracebackType
from typing import Any, List, Optional, Type, TypeVar

from twisted.internet import reactor
from twisted.internet.defer import Deferred, maybeDeferred
from twisted.python.failure import Failure
from twisted.python.log import PythonLoggingObserver

from . import command
from .client import TClient, VNCDoToolClient, VNCDoToolFactory, factory_connect

V = TypeVar("V")
TProxy = TypeVar("TProxy", bound="ThreadedVNCClientProxy")

__all__ = ["connect"]

log = logging.getLogger(__name__)

_THREAD: Optional[threading.Thread] = None


def shutdown() -> None:
    if not reactor.running:
        return

    reactor.callFromThread(reactor.stop)
    global _THREAD
    if _THREAD is not None:
        _THREAD.join()
        _THREAD = None


class ThreadedVNCClientProxy:
    def __init__(
        self, factory: Type[VNCDoToolFactory], timeout: Optional[float] = 60 * 60
    ) -> None:
        self.factory = factory
        self.queue: queue.Queue[Any] = queue.Queue()
        self._timeout = timeout
        self.protocol: Optional[VNCDoToolClient] = None

    def __enter__(self: TProxy) -> TProxy:
        return self

    def __exit__(self, *_: Any) -> None:
        self.disconnect()

    @property
    def timeout(self) -> Optional[float]:
        """Timeout in seconds for API requests."""
        return self._timeout

    @timeout.setter
    def timeout(self, timeout: float) -> None:
        """Timeout in seconds for API requests."""
        self._timeout = timeout

    def connect(
        self, host: str, port: int = 5900, family: socket.AddressFamily = socket.AF_INET
    ) -> None:
        def capture_protocol(protocol: TClient) -> TClient:
            self.protocol = protocol
            return protocol

        self.factory.deferred.addCallback(capture_protocol)
        reactor.callWhenRunning(factory_connect, self.factory, host, port, family)

    def disconnect(self) -> None:
        def disconnector(protocol: VNCDoToolClient) -> None:
            protocol.transport.loseConnection()

        reactor.callFromThread(self.factory.deferred.addCallback, disconnector)

    def __getattr__(self, attr: str) -> Any:
        method = getattr(self.factory.protocol, attr)

        def threaded_call(
            protocol: VNCDoToolClient, *args: Any, **kwargs: Any
        ) -> Deferred:
            def result_callback(result: V) -> V:
                self.queue.put(result)
                return result

            d = maybeDeferred(method, protocol, *args, **kwargs)
            d.addBoth(result_callback)
            return d

        def errback_not_connected(
            reason: Failure, *args: Any, **kwargs: Any
        ) -> Failure:
            self.queue.put(reason)
            return reason

        def callable_threaded_proxy(*args: Any, **kwargs: Any) -> Any:
            reactor.callFromThread(
                self.factory.deferred.addCallbacks,  # ensure we're connected
                threaded_call,
                errback_not_connected,
                args,
                kwargs,
            )
            try:
                result = self.queue.get(timeout=self._timeout)
            except queue.Empty:
                raise TimeoutError("Timeout while waiting for client response")

            if isinstance(result, Failure):
                result.raiseException()

            return result

        if callable(method):
            return callable_threaded_proxy
        else:
            return getattr(self.protocol, attr)

    def __dir__(self) -> List[str]:
        return dir(self.__class__) + dir(self.factory.protocol)


def connect(
    server: str,
    password: Optional[str] = None,
    factory_class: Type[VNCDoToolFactory] = VNCDoToolFactory,
    proxy: Type[ThreadedVNCClientProxy] = ThreadedVNCClientProxy,
    timeout: Optional[float] = None,
    username: Optional[str] = None,
) -> ThreadedVNCClientProxy:
    """Connect to a VNCServer and return a Client instance that is usable
    in the main thread of non-Twisted Python Applications, EXPERIMENTAL.

    >>> from vncdotool import api
    >>> with api.connect('host') as client
    >>>     client.keyPress('c')

    You may then call any regular VNCDoToolClient method on client from your
    application code.

    If you are using a GUI toolkit or other major async library please read
    http://twistedmatrix.com/documents/13.0.0/core/howto/choosing-reactor.html
    for a better method of intergrating vncdotool.
    """
    if not reactor.running:
        # ensure we kill reactor threads before trying to exit due to an Exception
        sys_excepthook = sys.excepthook

        def ensure_reactor_stopped(
            etype: Type[BaseException], value: BaseException, traceback: TracebackType
        ) -> None:
            shutdown()
            sys_excepthook(etype, value, traceback)

        sys.excepthook = ensure_reactor_stopped

        global _THREAD
        _THREAD = threading.Thread(
            target=reactor.run,
            name="Twisted",
            kwargs={"installSignalHandlers": False},
        )
        _THREAD.daemon = True
        _THREAD.name = "Twisted Reactor"
        _THREAD.start()

        observer = PythonLoggingObserver()
        observer.start()

    factory = factory_class()

    if username is not None:
        factory.username = username

    if password is not None:
        factory.password = password

    family, host, port = command.parse_server(server)
    client = proxy(factory, timeout)
    client.connect(host, port=port, family=family)

    return client


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    server = sys.argv[1]
    password = sys.argv[2]
    client1 = connect(server, password)
    client2 = connect(server, password)

    client1.captureScreen("screenshot.png")

    for key in "username":
        client2.keyPress(key)

    for key in "passw0rd":
        client1.keyPress(key)

    client1.disconnect()
    client2.disconnect()
    shutdown()
