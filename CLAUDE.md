# Conventions

Tests are stdlib `unittest`, not pytest. Run the unit suite with `make test`
(`python -m unittest discover tests/unit`) -- note the path: discovery over
plain `tests` also collects `tests/functional/`, whose tests need the Docker
Compose test server fleet (`make servers-up`) and fail loudly without it --
they never skip, so a down fleet can't pass as green.
Unit tests need no VNC server: protocol classes are driven directly with a
mocked Twisted transport (see `tests/unit/test_rfb.py` and `test_client.py`
for the patterns).

A worktree builds its own `.venv`: run any `make` target needing one (`test-func`,
`venv`, ...) and it creates `$(WORKDIR)/.venv` with an editable install of that
checkout. Never symlink another checkout's `.venv` in -- the editable install
still points at the checkout that created it, so a subprocess run via that venv
(`vncdo`, `vnclog`) exercises the other checkout's code while in-process imports
resolve to this one, and the two halves of a functional test disagree about what
they're testing. `assert_cli_under_test()` in `tests/functional/vncservers.py`
catches this. If venv creation fails on a too-old `python3` (a worktree may not
inherit a local, untracked mise/pyenv pin the way the main checkout does), pass
`make <target> PY=python3.11` or whichever interpreter satisfies `PYTHON_FLOOR`.

Never start the Twisted reactor in a unit test. `vncdotool/api.py` runs the
reactor in a daemon thread and a reactor cannot be restarted
(`docs/library.rst` documents this design), so a test that touches
`api.connect` poisons or hangs the rest of the run. The functional suite
(`make test-func`) is the place for whole-client behaviour: every scenario
shells out to the real `vncdo` CLI via `subprocess.run` against the fleet
(`tests/servers/docker-compose.yml`) rather than calling `api.connect()`,
so a hang is contained by the kernel reaping the subprocess rather than by
anything in-process. See `specs/testing-framework.md` and
`tests/functional/vncservers.py`.

A comment carries what the reader cannot get anywhere else: something
surprising, particular to this code, and absent from the language, the
library's documentation, the RFB specs and the code itself. A server
that ignores what it was asked, an ordering nothing enforces, an obvious
approach that does not work here. `loggingproxy.py` has the shape of it:
"SetEncodings only says what the client asked for, and a server may
ignore it."

The reader knows the tools and can read the code, and an AI reader has
every public document already. Anything they could look up, infer from a
name, or learn by running it is not worth writing, and neither is
anything about the change rather than the code -- the alternative you
rejected, what used to be here, who calls it, the issue or PR it came
from. That is commit-message and `docs/` material. Point elsewhere only
when there is something surprising there too long to state here.

Test by deleting it: keep it only if an intelligent reader would still
be surprised later. Shortening an unnecessary comment leaves an
unnecessary comment. One or two lines is the norm.

Check the protocol documents before implementing anything that touches the
wire -- a new encoding, security type, message or client command. The repo
carries no copy of the spec; `DEVELOP.rst` says which of RFC 6143 and
rfbproto covers what. Guessing a message layout from the surrounding code
produces something that works against one server and no other.

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
