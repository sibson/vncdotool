"""tests.functional.utils is imported for the skip/fail rule alone: it needs
no server and starts no reactor.
"""
from __future__ import annotations

import unittest
from typing import Dict, List, Mapping, Tuple

from tests.functional.utils import (
    TCP_SERVERS,
    VNCEV,
    VNCServer,
    absent_server_skips,
    os_servers,
    running_in_ci,
)

ENV_SAMPLES: Dict[str, Tuple[Mapping[str, str], bool]] = {
    "unset": ({}, False),
    "CI_empty": ({"CI": ""}, False),
    "CI_false": ({"CI": "false"}, False),
    "CI_0": ({"CI": "0"}, False),
    "GITHUB_ACTIONS_false": ({"GITHUB_ACTIONS": "false"}, False),
    "CI_true": ({"CI": "true"}, True),
    "CI_1": ({"CI": "1"}, True),
    "GITHUB_ACTIONS_true": ({"GITHUB_ACTIONS": "true"}, True),
    "both": ({"CI": "true", "GITHUB_ACTIONS": "true"}, True),
}

# Linux's OS-hosted server is registered only when the QEMU setup script has
# exported its opt-in, so os_servers("linux") is empty here and there is
# nothing to generate a case from.
NATIVE_PLATFORMS = ("darwin", "win32")

NEVER_SKIPPING = TCP_SERVERS + [VNCEV]


def native_servers() -> List[Tuple[str, VNCServer]]:
    return [(platform, server) for platform in NATIVE_PLATFORMS for server in os_servers(platform)]


class CIDetection:
    env: Mapping[str, str]
    is_ci: bool

    def test_says_whether_this_is_ci(self) -> None:
        self.assertEqual(running_in_ci(self.env), self.is_ci)  # type: ignore[attr-defined]


class NativeServerVerdict:
    server: VNCServer
    env: Mapping[str, str]
    is_ci: bool

    def test_skips_only_off_ci(self) -> None:
        self.assertEqual(  # type: ignore[attr-defined]
            absent_server_skips(self.server, self.env),
            not self.is_ci,
            f"{self.server.name} absent: a CI run must report a failure, a "
            "developer's run a skip",
        )


class ContainerServerVerdict:
    server: VNCServer
    env: Mapping[str, str]

    def test_never_skips(self) -> None:
        self.assertFalse(  # type: ignore[attr-defined]
            absent_server_skips(self.server, self.env),
            f"{self.server.name} is started by `make servers-up`, so a run "
            "without it must fail rather than pass as green",
        )


class TestNativeServersAreRegistered(unittest.TestCase):
    def test_every_supported_platform_has_one(self) -> None:
        for platform in NATIVE_PLATFORMS:
            self.assertTrue(
                os_servers(platform),
                f"no OS-hosted server registered for {platform}, so the cases "
                "generated below assert nothing",
            )


def _case(name: str, body: type, attrs: Dict[str, object], method: str) -> unittest.TestCase:
    return type(name, (body, unittest.TestCase), attrs)(method)


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: object) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestNativeServersAreRegistered))
    for env_name, (env, is_ci) in ENV_SAMPLES.items():
        suite.addTest(
            _case(
                f"TestCIDetection_{env_name}",
                CIDetection,
                {"env": env, "is_ci": is_ci},
                "test_says_whether_this_is_ci",
            )
        )
        for platform, server in native_servers():
            suite.addTest(
                _case(
                    f"TestNativeVerdict_{platform}_{server.name.replace('-', '_')}_{env_name}",
                    NativeServerVerdict,
                    {"server": server, "env": env, "is_ci": is_ci},
                    "test_skips_only_off_ci",
                )
            )
        for server in NEVER_SKIPPING:
            suite.addTest(
                _case(
                    f"TestContainerVerdict_{server.name.replace('-', '_')}_{env_name}",
                    ContainerServerVerdict,
                    {"server": server, "env": env},
                    "test_never_skips",
                )
            )
    return suite


if __name__ == "__main__":
    unittest.main()
