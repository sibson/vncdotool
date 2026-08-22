"""Functional tests against the VNC server hosted by the OS we run on.

Unlike the Docker servers in test_servers.py, these servers are part of the
operating system rather than something we build: UltraVNC installed as a
Windows service, Apple Screen Sharing / Remote Management on macOS, or a
raw QEMU started directly on Linux. The setup scripts live next to each
server's notes in tests/servers/ultravnc, tests/servers/screen-sharing, and
tests/servers/qemu-kvm, and are what CI runs before this module.

On a platform with no OS-hosted server described there is simply nothing
to register, and on a platform that has one but hasn't set it up the test
fails with the command that would set it up.
"""

from .vncservers import os_servers, register_server_tests

# Every scenario shells out to the vncdo CLI (see vncservers.run_vncdo), so
# no reactor ever starts in this process and no api.shutdown() is needed.
register_server_tests(os_servers(), globals())
