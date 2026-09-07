"""VeNCrypt against the live TigerVNC and wayvnc fleet."""

from unittest import TestCase

from PIL import Image

from vncdotool.command import ExitStatus

from .utils import (
    HOST,
    PNG_MAGIC,
    TIGERVNC_VENCRYPT,
    TIGERVNC_VENCRYPT_ANON,
    VENCRYPT_CA_CERT,
    WAYVNC,
    WAYVNC_CA_CERT,
    port_open,
    run_vncdo,
    screenshot_dir,
)

VENCRYPT = TIGERVNC_VENCRYPT._replace(extra_args=())
VENCRYPT_ANON = TIGERVNC_VENCRYPT_ANON._replace(extra_args=())
WAYVNC_BARE = WAYVNC._replace(extra_args=())

NO_PASSWORD = VENCRYPT._replace(password=None)
ANON_NO_PASSWORD = VENCRYPT_ANON._replace(password=None)


class _VeNCryptTestMixin:
    server = VENCRYPT

    def setUp(self) -> None:
        if not port_open(HOST, self.server.port):
            self.fail(
                f"{self.server.name} not reachable on {HOST}:{self.server.port} -- "
                f"{self.server.how_to_start}"
            )

    def assert_captured(self, server, *args: str) -> None:
        png = screenshot_dir() / f"{server.name}-{self.id().rsplit('.', 1)[-1]}.png"
        result = run_vncdo(server, *args, "capture", str(png))

        self.assertEqual(
            result.returncode,
            0,
            f"{server.name}: vncdo exited {result.returncode}, "
            f"stderr:\n{result.stderr}",
        )
        data = png.read_bytes()
        self.assertEqual(data[:8], PNG_MAGIC, f"{server.name}: not a PNG")
        with Image.open(png) as image:
            self.assertEqual(image.size, server.size)

    def assert_refused(self, server, *args: str) -> str:
        result = run_vncdo(server, *args, "pause", "0")

        self.assertEqual(
            result.returncode,
            ExitStatus.PROTOCOL_ERROR,
            f"{server.name}: expected a reported protocol error, got "
            f"{result.returncode}; stderr:\n{result.stderr}",
        )
        return result.stderr


class TestVeNCryptX509(_VeNCryptTestMixin, TestCase):
    server = VENCRYPT

    def test_x509_vnc_connects_when_the_certificate_verifies(self) -> None:
        self.assert_captured(VENCRYPT, "--tls-ca-cert", str(VENCRYPT_CA_CERT))

    def test_x509_none_is_taken_when_no_password_was_given(self) -> None:
        self.assert_captured(NO_PASSWORD, "--tls-ca-cert", str(VENCRYPT_CA_CERT))

    def test_an_unverifiable_certificate_is_refused_by_default(self) -> None:
        stderr = self.assert_refused(VENCRYPT)

        self.assertIn("--tls-ca-cert", stderr)
        self.assertIn("--tls-insecure-skip-verify", stderr)

    def test_the_insecure_flag_accepts_the_certificate_anyway(self) -> None:
        self.assert_captured(VENCRYPT, "--tls-insecure-skip-verify")


class TestVeNCryptAnonymous(_VeNCryptTestMixin, TestCase):
    server = VENCRYPT_ANON

    def test_anonymous_tls_is_refused_by_default(self) -> None:
        stderr = self.assert_refused(VENCRYPT_ANON)

        self.assertIn("--tls-insecure-skip-verify", stderr)

    def test_tls_vnc_connects_with_the_insecure_flag(self) -> None:
        self.assert_captured(VENCRYPT_ANON, "--tls-insecure-skip-verify")

    def test_tls_none_is_taken_when_no_password_was_given(self) -> None:
        self.assert_captured(ANON_NO_PASSWORD, "--tls-insecure-skip-verify")


class TestWayvnc(_VeNCryptTestMixin, TestCase):
    server = WAYVNC_BARE

    def test_x509_plain_captures_a_screen(self) -> None:
        self.assert_captured(WAYVNC_BARE, "--tls-ca-cert", str(WAYVNC_CA_CERT))

    def test_an_unverifiable_certificate_is_refused_by_default(self) -> None:
        result = run_vncdo(WAYVNC_BARE, "pause", "0")

        self.assertNotEqual(
            result.returncode,
            0,
            f"vncdo accepted an unverified certificate; stderr:\n{result.stderr}",
        )
        self.assertIn("--tls-insecure-skip-verify", result.stderr)

    def test_the_insecure_flag_accepts_the_certificate_anyway(self) -> None:
        self.assert_captured(WAYVNC_BARE, "--tls-insecure-skip-verify")
