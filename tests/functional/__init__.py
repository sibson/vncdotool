"""Functional test helpers and fixtures."""
from pathlib import Path
from typing import Optional
from unittest import TestLoader, TestSuite


def load_tests(loader: TestLoader, standard_tests: TestSuite, pattern: Optional[str]) -> TestSuite:
    from .utils import assert_cli_installed

    assert_cli_installed()
    here = Path(__file__).resolve().parent
    standard_tests.addTests(
        loader.discover(start_dir=str(here), pattern=pattern or "test*.py", top_level_dir=str(here.parents[1]))
    )
    return standard_tests
