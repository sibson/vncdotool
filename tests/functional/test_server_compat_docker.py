"""Functional tests against the Docker Compose VNC test servers.

See tests/servers/docker-compose.yml and tests/servers/servers.mk. The test
servers are expected to already be running (e.g. via ``make servers-up``)
before this module executes; a server whose port isn't open fails with a
clear message rather than passing silently as skipped.

The servers themselves, and the round trip run against each of them, are
described in utils.py and shared with the OS-hosted servers tested by
test_server_compat_native.py.

Screenshots captured here are kept rather than thrown away: each one is
written to the screenshots directory (``tests/servers/screenshots`` by
default, override with ``VNCDOTOOL_SCREENSHOT_DIR``) so that a failing or
suspicious capture can be looked at directly after the run.
"""

from .utils import DOCKER_SERVERS, register_server_tests

# Every scenario shells out to the vncdo CLI (see utils.run_vncdo), so
# no reactor ever starts in this process and no api.shutdown() is needed.
register_server_tests(DOCKER_SERVERS, globals())
