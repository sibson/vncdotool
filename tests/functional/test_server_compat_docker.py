"""The fast path: can we talk to a VNC server at all.

Not a per-server grid. Running the same round trip against every fleet
member proves the harness works seven times over and nothing else, because
whatever distinguishes a server is tested where that distinction lives:
the security types in test_vencrypt.py, the transports in
test_websocket.py, the encodings and pixel formats in test_encodings.py and
test_pixel_format.py, and the in-process API against
libvncserver-example in test_api_lifecycle.py.

So this module runs one server, first, and cheaply. A fleet that is down,
stale or unreachable fails here in seconds rather than part-way through the
suites that take minutes. The per-server grid that remains is
test_server_compat_native.py, where an OS-hosted server has no other
coverage at all.

Screenshots captured here are kept rather than thrown away: each one is
written to the screenshots directory (``tests/servers/screenshots`` by
default, override with ``VNCDOTOOL_SCREENSHOT_DIR``) so that a failing or
suspicious capture can be looked at directly after the run.
"""

from .utils import TIGERVNC, register_server_tests

# Every scenario shells out to the vncdo CLI (see utils.run_vncdo), so
# no reactor ever starts in this process and no api.shutdown() is needed.
register_server_tests([TIGERVNC], globals())
