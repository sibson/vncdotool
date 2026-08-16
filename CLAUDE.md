# Conventions

Tests are stdlib `unittest`, not pytest. Run the unit suite with `make test`
(`python -m unittest discover tests/unit`) -- note the path: discovery over
plain `tests` also collects `tests/functional/`, whose tests need the Docker
Compose test server fleet (`make servers-up`) and fail loudly without it --
they never skip, so a down fleet can't pass as green.
Unit tests need no VNC server: protocol classes are driven directly with a
mocked Twisted transport (see `tests/unit/test_rfb.py` and `test_client.py`
for the patterns).

Never start the Twisted reactor in a unit test. `vncdotool/api.py` runs the
reactor in a daemon thread and a reactor cannot be restarted
(`docs/library.rst` documents this design), so a test that touches
`api.connect` poisons or hangs the rest of the run. The functional suite
(`make test-func`) is the place for whole-client behaviour: every scenario
shells out to the real `vncdo` CLI via `subprocess.run` against the fleet
(`tests/servers/docker-compose.yml`) rather than calling `api.connect()`,
so a hang is contained by the kernel reaping the subprocess rather than by
anything in-process. See `docs/testing-framework-design.md` and
`tests/functional/vncservers.py`.

Keep comments and docstrings short. A comment earns its place by recording
a *why* the code cannot show -- a protocol quirk, a server's misbehaviour,
why the obvious alternative was rejected. One or two lines is the norm; a
longer block needs a reason to be longer. Do not restate what the next line
does, and do not narrate what a change replaced -- that belongs in the
commit message. Design rationale belongs in `docs/`.

A cross-reference is worth a clause when it saves the reader real work
(`see docs/capture.rst`), so an explanation lives in exactly one place
rather than being repeated. What it must not become is a paragraph
re-explaining what the other file already says.

Lint is plain flake8, configured in `setup.cfg`: line length 127,
`extend-ignore = E203`. CI runs `flake8 --count --statistics vncdotool tests`,
so run that before pushing. No black, no isort.

Every user-visible fix gets a `CHANGELOG.rst` entry under the current
`(UNRELEASED)` heading, in the form `- <description> (@author, #NNN)`.

Tests live in topical files -- `test_rfb.py` (wire protocol),
`test_client.py` (client commands), `test_command.py` (CLI). A
`tests/unit/test_issue_NNN.py` is a triage artifact, not a permanent home: it
exists so an open issue has a runnable reproduction attached to it. When you
fix the underlying bug, move the test into the topical file, drop its
`@unittest.expectedFailure` marker, and rename it for the behaviour it checks
rather than the issue number.

# Release Process

Version lives in `vncdotool/__init__.py` and is bumped by the release target.
Always release from `main`; the target runs the unit tests, stamps
`CHANGELOG.rst`, tags `vX.Y.Z`, and pushes:

    make release
