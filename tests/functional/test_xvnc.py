import tempfile
from shutil import which
from unittest import skipUnless

from pyvirtualdisplay import Display

from vncdotool import api


@skipUnless(which("xvnc"), reason="requires Xvnc")
def test_color_xvnc() -> None:
    with tempfile.NamedTemporaryFile(prefix="vnc_", suffix=".png") as png:

        with Display(backend="xvnc", rfbport=5900 + 9876):
            with api.connect("localhost:9876") as client:
                client.timeout = 1
                client.captureScreen(png.name)

        with tempfile.NamedTemporaryFile(prefix="passwd_", delete=False) as passwd_file:
            password = "123456"
            vncpasswd_generated = b"\x49\x40\x15\xf9\xa3\x5e\x8b\x22"
            passwd_file.write(vncpasswd_generated)
            passwd_file.close()
            with Display(backend="xvnc", rfbport=5900 + 1234, rfbauth=passwd_file.name):
                with api.connect("localhost:1234", password=password) as client:
                    client.timeout = 1
                    client.captureScreen(png.name)
