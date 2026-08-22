

Running Tests
------------------------

Install uv_, then::

    make test

``uv run`` resolves the interpreter from ``.python-version``, downloading it
if needed, and syncs an editable install of vncdotool plus the dev
dependency group into ``.venv`` before running -- unit tests need nothing
else set up first.

The functional tests exercise the real ``vncdo`` CLI via ``subprocess.run``
against the Docker Compose VNC test server fleet, which needs to be
running::

    make servers-up
    make test-func

The console scripts are named by full path, taken from the directory of
the interpreter running the tests, so the CLI exercised is always the one
installed alongside it -- no ``PATH`` setup, and no way for another
checkout's ``vncdo`` to stand in. A server that isn't reachable fails its
tests rather than being skipped, so a down fleet cannot pass as green.

Coverage
------------------------

::

    make coverage

runs both suites under coverage and writes ``htmlcov/index.html``. The
targets are separate from ``make test`` because measuring costs runtime
that is not worth paying on every edit-run loop.

Almost everything the functional suite covers happens in a ``vncdo``,
``vnclog`` or ``vncdo-replay`` subprocess, which a plain ``coverage run``
does not see. ``patch = subprocess`` in ``pyproject.toml`` is what measures
them, so it needs coverage 7.10 or newer. A child that is ``kill``\ ed
rather than asked to stop never gets to write its data, so tests that
stop a long-running process terminate it and let Twisted's SIGTERM
handler shut the reactor down.

CI reports the unit and fleet tiers separately as well as combined. Two
tiers, two meanings: a fall in the unit number is a regression in the
diff, while a fall in the fleet number can also mean a server container
did not come up. Nothing is gated -- there is no threshold, and no build
fails on the number.

The numbers are at the top of the run's job summary, one line per tier,
with the per-file tables folded away underneath and ``coverage-html`` an
artifact on the same run.

The browsable report is https://app.codecov.io/gh/sibson/vncdotool --
line-by-line annotation, history, and the ``unit`` and ``fleet`` flags
graphed separately. CI uploads one Cobertura file per tier there.

The upload uses the ``CODECOV_TOKEN`` secret, which a pull request from
a fork cannot read, so those runs skip it and report through the job
summary alone.

``codecov.yml`` turns the project and patch status checks off and
suppresses the PR comment, so Codecov observes and never votes.

``.github/scripts/coverage-summary.sh unit=DIR fleet=DIR`` is what CI
runs. It writes ``combined/summary.md`` and prints it, so the same report
can be produced locally.

Decode performance
------------------------

Two numbers come out of replaying a captured frame against the decode
path, and they are not equally trustworthy::

    make bench           # time it, touching nothing
    make bench-record    # time it and append a row to bench.jsonl
    make bench-report    # tabulate the rows, ARGS=--diff to compare two

Timings are only comparable against timings from the same machine, which
is why every row carries a ``machine`` digest of the CPU, core count and
OS, and why the report leaves the delta blank across a change of
interpreter or Pillow. Call counts carry no such caveat: the same fixture
bytes produce the same counts anywhere, so they are the number that
compares across machines and across history.

``bench.jsonl`` is a series a person appends to deliberately. Recording
refuses on a dirty tree, because a row names a commit and one measured
against uncommitted changes describes a tree nobody can check out again.
CI never writes to it.

What CI does instead is count the base branch and the pull request with
the same harness, and comment only when they differ. The baseline is the
base branch itself rather than a recorded row, so a change stops being
reported once it has landed.

Finding a regression that already landed
..........................................

Counts are exact and reproducible at any commit, which makes them a
``git bisect`` predicate. Record what the counts should be, then let
bisect find the commit that changed them::

    git bisect start <bad> <good>
    git bisect run sh -c \
      'uv run python -m tests.goldens.benchmark --counts > /tmp/c.json && cmp -s /tmp/c.json good.json'

where ``good.json`` came from ``--counts`` at the good commit. Timings can
bisect the same way if the regression is in how long the work takes rather
than how much of it there is, but give them a threshold rather than an
equality, and expect noise to cost a few extra steps.

``--counts`` only exists from the commit that introduced it, so a bisect
reaching further back has to supply the harness rather than rely on the
one in the tree: check ``tests/goldens`` out of a recent ref at the top of
the predicate, since only ``vncdotool/`` needs to be the commit under
test.


Working with more than one checkout
------------------------------------

uv keys its project environment to the project directory, so each working
tree gets **its own** ``.venv`` automatically; run ``uv run`` or ``make`` in
it and one is built.

Do not symlink or reuse another checkout's ``.venv``. An editable install
records the path it was created from, so its ``vncdotool``, and the
``vncdo`` console script beside it, still point at the original checkout.
Tests run through it then pass against code from somewhere else, and a
change looks landed when it was never exercised.


The RFB/VNC Protocol
------------------------

Two documents cover RFB, and which one answers a question depends on how
far past the baseline it sits.

`RFC 6143`_ is the normative specification. It defines RFB 3.8 and the
encodings and security types that shipped with it, and it is the one to
cite when the wire format is in dispute.

rfbproto_ is a community effort to document everything servers grew
afterwards: the later encodings and pseudo-encodings, the security types,
the message extensions, and the vendor quirks the RFC never covered.
Reach for it whenever the answer is not in the RFC -- which, for most of
what vncdotool implements, it is not.

rfbproto is a living document with no releases or version numbers, so link
a commit permalink rather than ``master`` when a comment depends on its
wording. It is one grep-able reStructuredText file, so clone it into
``docs/rfbproto`` (git-ignored) and read it locally rather than fetching
sections over the web::

    git clone https://github.com/rfbproto/rfbproto.git docs/rfbproto

Neither document describes how any particular server actually behaves; where
one is known to diverge, ``specs/server-compatibility-plan.md`` records what
we do about it.


Preparing a Release
------------------------
  1. ensure CHANGELOG.rst contains correct version
  1. ``make version-new-version-number``
  1. ``make release``
  1. blog post/twitter

.. _RFC 6143: https://www.rfc-editor.org/rfc/rfc6143
.. _rfbproto: https://github.com/rfbproto/rfbproto/blob/master/rfbproto.rst
.. _uv: https://docs.astral.sh/uv/getting-started/installation/
