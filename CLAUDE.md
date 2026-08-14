# Conventions

Tests are stdlib `unittest`, not pytest. Run the unit suite with `make test`
(`python -m unittest discover tests/unit`) -- note the path: discovery over
plain `tests` also collects `tests/functional/`, whose harness shells out to
build libvncserver and fails on machines without the toolchain. Unit tests
need no VNC server: protocol classes are driven directly with a mocked
Twisted transport (see `tests/unit/test_rfb.py` and `test_client.py` for the
patterns).

Never start the Twisted reactor in a unit test. `vncdotool/api.py` runs the
reactor in a daemon thread and a reactor cannot be restarted
(`docs/library.rst` documents this design), so a test that touches
`api.connect` poisons or hangs the rest of the run. The functional suite
(`make test-func`) is the place for whole-client behaviour; it needs
libvncserver's example server (`make libvnc-examples`) on the PATH.

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

# Comments

Default to no comments. Add one only when the WHY is non-obvious: a hidden
constraint, a subtle invariant, a workaround for a specific bug, behaviour
that would surprise a reader. Don't explain WHAT the code does -- well-named
identifiers already do that. Don't reference the current task, fix, or
callers ("used by X", "added for the Y flow", "handles the case from issue
#123") -- that belongs in the commit message, not the code.

# Release Process

Version lives in `vncdotool/__init__.py` and is bumped by the release target.
Always release from `main`; the target runs the unit tests, stamps
`CHANGELOG.rst`, tags `vX.Y.Z`, and pushes:

    make release
