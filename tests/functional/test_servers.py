"""Functional tests against the Docker Compose VNC test servers.

See tests/servers/docker-compose.yml and tests/servers/servers.mk. The test
servers are expected to already be running (e.g. via ``make servers-up``)
before this module executes; a server whose port isn't open is skipped with
a clear message rather than failing the whole run, so this module is also
safe to run outside of that make target.

The servers themselves, and the round trip run against each of them, are
described in vncservers.py and shared with the OS-hosted servers tested by
test_os_servers.py.

Screenshots captured here are kept rather than thrown away: each one is
written to the screenshots directory (``tests/servers/screenshots`` by
default, override with ``VNCDOTOOL_SCREENSHOT_DIR``) so that a failing or
suspicious capture can be looked at directly after the run.
"""

from vncdotool import api

from .vncservers import DOCKER_SERVERS, register_server_tests

register_server_tests(DOCKER_SERVERS, globals())


def tearDownModule() -> None:
    # api.connect() starts a background Twisted reactor thread that
    # outlives any individual client connection. Without stopping it here,
    # the interpreter (and `unittest discover`) hangs on exit after all
    # tests in this module have finished.
    api.shutdown()
