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

Every reader pays for every comment; almost none of them needed it.
Default to writing none.

A comment earns its place only when being wrong about this would be
*silent* -- code that looks right, runs, passes, and is wrong anyway. A
protocol quirk, a server that lies, an ordering nothing enforces. When
the mistake breaks loudly instead -- CI red, a test failing, an
exception, a name that already says it -- the failure is the
documentation, and the comment is noise. "Someone might otherwise
change this" is not a reason: they will change it, it will break, and
they will know within a minute.

Write for a competent reader. Do not explain what a named option does,
restate the next line, guard against carelessness, or record how the
code reached its current state -- the alternative you rejected, the
thing that used to be here, who calls it, which issue it came from.
That is commit-message material, and design rationale is `docs/`
material. A pointer to prose elsewhere is not a reason to add a comment:
if the code does not need one, it does not need a `see DEVELOP.rst`
either.

Test by deleting it. Keep it only if the reader would then be *wrong*,
not merely less informed. Shortening an unnecessary comment leaves an
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
