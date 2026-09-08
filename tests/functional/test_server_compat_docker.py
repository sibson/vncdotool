"""The fast path: can we talk to one VNC server at all.

Not a per-server grid. What distinguishes a server is tested where that
distinction lives; the only per-server grid left is
test_server_compat_native.py, where an OS-hosted server has no other
coverage.

Screenshots captured here are kept rather than thrown away: each one is
written to the screenshots directory (``tests/servers/screenshots`` by
default, override with ``VNCDOTOOL_SCREENSHOT_DIR``) so that a failing or
suspicious capture can be looked at directly after the run.
"""

from .utils import TIGERVNC, register_server_tests

# Every scenario shells out to the vncdo CLI (see utils.run_vncdo), so
# no reactor ever starts in this process and no api.shutdown() is needed.
register_server_tests([TIGERVNC], globals())
