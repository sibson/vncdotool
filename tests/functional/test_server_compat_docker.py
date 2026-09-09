"""The critical user journey: connect, send input, capture a screen.

Run first and cheaply, so `vncdo` breaking outright fails here rather than
part-way through the suites that take minutes.

TigerVNC is the fast path. libvncserver-example is here because it has no X
server, so it cannot run the scene player and cannot join the encoding and
pixel-format grids; without these four cases nothing sends it a key press or
a pointer event.

Screenshots captured here are kept rather than thrown away: each one is
written to the screenshots directory (``tests/servers/screenshots`` by
default, override with ``VNCDOTOOL_SCREENSHOT_DIR``) so that a failing or
suspicious capture can be looked at directly after the run.
"""

from .utils import LIBVNCSERVER_EXAMPLE, TIGERVNC, register_server_tests

# Every scenario shells out to the vncdo CLI (see utils.run_vncdo), so
# no reactor ever starts in this process and no api.shutdown() is needed.
register_server_tests([TIGERVNC, LIBVNCSERVER_EXAMPLE], globals())
