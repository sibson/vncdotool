from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FLEET_TAG_SCRIPT = REPO / "tests" / "servers" / "fleet-tag.sh"

# The `--from=` line names a path inside that stage, which does not exist in
# the fixture tree: every run here fails if the script tries to hash it.
DOCKERFILE = """\
FROM debian:bookworm-slim AS base
COPY servers/entrypoint.sh /entrypoint.sh
COPY goldens/scenes/ /tests/goldens/scenes/
COPY --from=base /usr/bin/true /usr/local/bin/true
"""

COMPOSE = """\
services:
  tigervnc:
    build:
      context: ..
      dockerfile: servers/Dockerfile
      target: base
"""

FIXTURE_FILES = {
    "tests/servers/Dockerfile": DOCKERFILE,
    "tests/servers/docker-compose.yml": COMPOSE,
    "tests/servers/entrypoint.sh": "#!/bin/sh\nexec sleep infinity\n",
    "tests/servers/PORTS.md": "| service | port |\n| ------- | ---- |\n",
    "tests/goldens/scenes/scene.txt": "a scene\n",
}

# A GIT_DIR or GIT_INDEX_FILE inherited from the runner would point the
# script at another repository entirely.
CLEAN_ENV = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, env=CLEAN_ENV, capture_output=True, text=True, check=True
    )
    return result.stdout


def run_script(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(repo / "tests" / "servers" / "fleet-tag.sh")],
        cwd=repo, env=CLEAN_ENV, capture_output=True, text=True,
    )


class FleetTagTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)

        for name, content in FIXTURE_FILES.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        shutil.copy2(FLEET_TAG_SCRIPT, self.repo / "tests" / "servers" / "fleet-tag.sh")

        git(self.repo, "-c", "init.defaultBranch=main", "init", "-q")
        git(self.repo, "config", "user.email", "fleet@example.invalid")
        git(self.repo, "config", "user.name", "Fleet Fixture")
        self.commit()

    def commit(self, message: str = "fixture") -> None:
        git(self.repo, "add", "--all")
        git(self.repo, "commit", "-q", "-m", message)

    def tag(self) -> str:
        result = run_script(self.repo)
        self.assertEqual(result.returncode, 0, f"fleet-tag.sh failed:\n{result.stderr}")
        return result.stdout.strip()

    def write(self, name: str, content: str) -> None:
        (self.repo / name).write_text(content)

    def test_a_clean_tree_tags_the_same_way_twice(self) -> None:
        self.assertEqual(self.tag(), self.tag())

    def test_an_uncommitted_edit_to_a_copy_source_changes_the_tag(self) -> None:
        before = self.tag()

        self.write("tests/servers/entrypoint.sh", "#!/bin/sh\nexec sleep 1\n")

        self.assertNotEqual(before, self.tag())

    def test_reverting_an_uncommitted_edit_restores_the_tag(self) -> None:
        before = self.tag()
        original = (self.repo / "tests" / "servers" / "entrypoint.sh").read_text()

        self.write("tests/servers/entrypoint.sh", "#!/bin/sh\nexec sleep 1\n")
        self.write("tests/servers/entrypoint.sh", original)

        self.assertEqual(before, self.tag())

    def test_committing_an_edit_does_not_change_its_tag(self) -> None:
        self.write("tests/servers/entrypoint.sh", "#!/bin/sh\nexec sleep 1\n")
        built_from = self.tag()

        self.commit("edit the entrypoint")

        self.assertEqual(built_from, self.tag())

    def test_an_untracked_copy_source_changes_the_tag(self) -> None:
        before = self.tag()

        self.write("tests/goldens/scenes/added.txt", "another scene\n")

        self.assertNotEqual(before, self.tag())

    def test_a_gitignored_file_under_a_copy_source_does_not_change_the_tag(self) -> None:
        self.write(".gitignore", "tests/goldens/scenes/*.png\n")
        self.commit("ignore generated scenes")
        before = self.tag()

        self.write("tests/goldens/scenes/generated.png", "not really a png\n")

        self.assertEqual(before, self.tag())

    def test_committing_documentation_does_not_change_the_tag(self) -> None:
        before = self.tag()

        self.write("tests/servers/PORTS.md", "| service | port |\n| ------- | ---- |\n| a | 1 |\n")
        self.commit("document a port")

        self.assertEqual(before, self.tag())

    def test_editing_the_dockerfile_changes_the_tag(self) -> None:
        before = self.tag()

        self.write("tests/servers/Dockerfile", DOCKERFILE + "ENV PROBE=1\n")

        self.assertNotEqual(before, self.tag())

    def test_editing_the_compose_file_changes_the_tag(self) -> None:
        before = self.tag()

        self.write("tests/servers/docker-compose.yml", COMPOSE.replace("target: base", "target: other"))

        self.assertNotEqual(before, self.tag())

    def test_the_repositorys_own_index_is_left_alone(self) -> None:
        self.write("tests/servers/entrypoint.sh", "#!/bin/sh\nexec sleep 1\n")
        git(self.repo, "add", "tests/servers/entrypoint.sh")
        staged = git(self.repo, "diff", "--cached", "--name-only")

        self.tag()

        self.assertEqual(staged, git(self.repo, "diff", "--cached", "--name-only"))

    def test_a_tree_without_a_git_store_fails(self) -> None:
        shutil.rmtree(self.repo / ".git")

        self.assertNotEqual(run_script(self.repo).returncode, 0)


class RepositoryDockerfileTests(unittest.TestCase):
    def test_the_checked_in_dockerfile_yields_a_tag(self) -> None:
        """Every COPY form the real Dockerfile uses is one the awk can read."""
        result = run_script(REPO)

        self.assertEqual(result.returncode, 0, f"fleet-tag.sh failed:\n{result.stderr}")
        self.assertRegex(result.stdout.strip(), r"^[0-9a-f]{40}$")
