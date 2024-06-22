""" Helpers to allow vncdotool to be intergrated into other applications.

.. warning::
    EXPERIMENTAL.
    This feature is under development, your help testing and debugging is appreciated.
"""

from __future__ import annotations

import logging
import queue
import socket
import sys
import threading
from types import TracebackType
from typing import Any, TypeVar, overload

from twisted.internet import reactor
from twisted.internet.defer import Deferred, maybeDeferred
from twisted.python.failure import Failure
from twisted.python.log import PythonLoggingObserver

from . import command
from .client import TClient, VNCDoToolClient, VNCDoToolFactory, factory_connect

V = TypeVar("V")
TProxy = TypeVar("TProxy", bound="ThreadedVNCClientProxy")

__all__ = ["shutdown", "connect"]

log = logging.getLogger(__name__)

_THREAD: threading.Thread | None = None


def shutdown() -> None:
    """Shutdown background thread running Twisted reactor."""
    if not reactor.running:
        return

    reactor.callFromThread(reactor.stop)
    global _THREAD
    if _THREAD is not None:
        _THREAD.join()
        _THREAD = None


class ThreadedVNCClientProxy:
    def __init__(
        self, factory: type[VNCDoToolFactory], timeout: float | None = 60 * 60
    ) -> None:
        self.factory = factory
        self.queue: queue.Queue[Any] = queue.Queue()
        self.timeout = timeout
        self.protocol: VNCDoToolClient | None = None

    def __enter__(self: TProxy) -> TProxy:
        return self

    def __exit__(self, *_: Any) -> None:
        self.disconnect()

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
        if not callable(method):
            return getattr(self.protocol, attr)

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
                result = self.queue.get(timeout=self.timeout)
            except queue.Empty:
                raise TimeoutError("Timeout while waiting for client response")

            if isinstance(result, Failure):
                result.raiseException()

            return result

        return callable_threaded_proxy

    def __dir__(self) -> list[str]:
        return dir(self.__class__) + dir(self.factory.protocol)


@overload
def connect(server: str) -> ThreadedVNCClientProxy: ...
@overload
def connect(server: str, password: str | None) -> ThreadedVNCClientProxy: ...
@overload
def connect(server: str, password: str | None, factory_class: type[VNCDoToolFactory]) -> ThreadedVNCClientProxy: ...
@overload
def connect(server: str, password: str | None, factory_class: type[VNCDoToolFactory], proxy: type[TProxy]) -> TProxy: ...
@overload
def connect(server: str, password: str | None, factory_class: type[VNCDoToolFactory], proxy: type[TProxy], timeout: float | None) -> TProxy: ...
@overload
def connect(server: str, password: str | None, factory_class: type[VNCDoToolFactory], proxy: type[TProxy], timeout: float | None, username: str | None) -> TProxy: ...
def connect(
    server: str,
    password: str | None = None,
    factory_class: type[VNCDoToolFactory] = VNCDoToolFactory,
    proxy: type[ThreadedVNCClientProxy] = ThreadedVNCClientProxy,
    timeout: float | None = None,
    username: str | None = None,
) -> ThreadedVNCClientProxy:
    """Connect to a VNCServer and return a Client instance that is usable
    in the main thread of non-Twisted Python Applications,

    >>> from vncdotool import api
    >>> with api.connect('host') as client
    >>>     client.keyPress('c')

    You may then call any regular :py:class:`VNCDoToolClient` method on client from your
    application code.

    If you are using a GUI toolkit or other major async library please read
    `Choosing a Reactor and GUI Toolkit Integration
    <https://docs.twistedmatrix.com/en/stable/core/howto/choosing-reactor.html>`_
    for a better method of intergrating vncdotool.
    """
    if not reactor.running:
        # ensure we kill reactor threads before trying to exit due to an Exception
        sys_excepthook = sys.excepthook

        def ensure_reactor_stopped(
            etype: type[BaseException],
            value: BaseException,
            traceback: TracebackType | None,
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
