"""Functional tests against the VNC server hosted by the OS we run on.

Unlike the Docker servers in test_servers.py, these servers are part of the
operating system rather than something we build: UltraVNC installed as a
Windows service, or Apple Screen Sharing / Remote Management on macOS. The
setup scripts live next to each server's notes in tests/servers/ultravnc
and tests/servers/screen-sharing, and are what CI runs before this module.

On a platform with no OS-hosted server described (Linux, say) there is
simply nothing to register, and on a platform that has one but hasn't set
it up the test skips with the command that would set it up.
"""

from vncdotool import api

from .vncservers import os_servers, register_server_tests

register_server_tests(os_servers(), globals())


def tearDownModule() -> None:
    # api.connect() starts a background Twisted reactor thread that
    # outlives any individual client connection. Without stopping it here,
    # the interpreter (and `unittest discover`) hangs on exit after all
    # tests in this module have finished.
    api.shutdown()
