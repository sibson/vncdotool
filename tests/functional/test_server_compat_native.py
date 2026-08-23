"""Functional tests against the VNC server native to the machine running them.

Unlike the Docker servers in test_server_compat_docker.py, these run raw on
the host rather than in a container: UltraVNC installed as a Windows
service, Apple Screen Sharing / Remote Management on macOS, or a raw QEMU
started directly on Linux. The setup scripts live next to each server's
notes in tests/servers/ultravnc, tests/servers/screen-sharing, and
tests/servers/qemu-kvm, and are what CI runs before this module.

On a platform with no native server described there is simply nothing to
register, and on a platform that has one but hasn't set it up the test
fails with the command that would set it up.
"""

from .utils import os_servers, register_server_tests

# Every scenario shells out to the vncdo CLI (see utils.run_vncdo), so
# no reactor ever starts in this process and no api.shutdown() is needed.
register_server_tests(os_servers(), globals())
