# Writing a vncdotool regression test

The unit suite is conventional stdlib `unittest` — ordinary `TestCase`
subclasses, ordinary `setUp` — so unlike some sibling projects there are no
naming tricks to learn. The traps here are different: two of them produce a
test that silently never ran or a run that hangs, and both look like your
repro failed when it didn't.

## The conventions, and the two traps

**stdlib `unittest`, not pytest.** pytest is neither installed nor used. Use
`self.assertEqual` and friends, not bare `assert`. Files go in `tests/unit/`
named `test_*.py`; discovery finds them, no registration.

**Trap 1 — discover `tests/unit`, never `tests`.** The runner is
`python -m unittest discover tests/unit` (what `make test` and CI run).
`discover tests` also collects `tests/functional/`, whose harness shells out to
`make -f libvncserver.mk libvnc-examples` and starts configuring a C library —
on a machine without the toolchain it dies with a `CalledProcessError` wall
that buries your test's result entirely.

**Trap 2 — never touch the reactor.** No unit test may import-and-use
`vncdotool.api.connect` or otherwise start the Twisted reactor.
`docs/library.rst` documents the design: the reactor runs in a daemon thread
and *cannot be restarted*, so a test that starts it poisons every test after
it, and a test that waits on it can hang the run. Unit tests drive the
protocol classes directly; the reactor never spins.

**No VNC server.** Instantiate the protocol class and mock the Twisted plumbing:

```python
self.client = client.VNCDoToolClient()
self.client.transport = mock.Mock()
self.client.factory = mock.Mock()
```

The suite type-annotates (`def setUp(self) -> None:`) and marks method
mocks with `# type: ignore[assignment]` — match that style.

## Driving the client

Three patterns, all proven in the existing suite:

**Replay server bytes.** `RFBClient` buffers incoming data in `self._packet`
(a bytearray) and consumes it via `self._handler()`. Append bytes and call the
handler — this is how `tests/unit/test_rfb.py` walks the client through
handshakes and auth failures without a server:

```python
self.client._packet += (
    b"RFB 003.003\n"      # protocol handshake
    b"\x00\x00\x00\x00"   # AuthTypes.INVALID
    b"\x00\x00\x00\x1a"
    b"Too many security failures"
)
self.client._handler()
self.client.transport.loseConnection.assert_called_once()
```

For post-handshake traffic, `dataReceived(bytes)` appends and drives the state
machine in one call.

**Mock the outgoing side and assert on calls.** To observe what the client
*sends* rather than parse it back out of the transport, replace the base-class
senders and assert — the `tests/unit/test_client.py` pattern:

```python
self.client.keyEvent = mock.Mock()  # type: ignore[assignment]
self.client.keyPress('ctrl-alt-del')
self.client.keyEvent.assert_any_call(Key.ControlLeft, down=1)
```

**CLI command dispatch.** `tests/unit/test_command.py` calls
`command.build_command_list(mock_factory, 'key a'.split())` and asserts
`factory.deferred.addCallback.assert_called_with(client.keyPress, 'a')` —
no reactor, no connection.

## Shape

```python
import unittest
from unittest import TestCase, mock

from vncdotool import client


class TestIssueNNN(TestCase):
    """<symptom, one line — mechanism not story>.

    https://github.com/sibson/vncdotool/issues/NNN

    Expected: <what the reporter should have seen>.
    Actual:   <what the code does instead>.

    TRIAGE ARTIFACT -- this file is temporary. When the fix lands, move this
    test into tests/unit/<home>.py, drop the expectedFailure marker, rename
    it for the behaviour it checks rather than the issue number, and delete
    this file.
    """

    def setUp(self) -> None:
        self.client = client.VNCDoToolClient()
        self.client.transport = mock.Mock()
        self.client.factory = mock.Mock()

    @unittest.expectedFailure
    def test_<behaviour>(self) -> None:
        ...  # drive with one of the three patterns above, assert the expectation
```

The docstring's expected-vs-actual and the issue URL are load-bearing: six
months from now they are the only context anyone has.

## Why `expectedFailure`

The test lands before the fix, so it has to fail. `expectedFailure` keeps CI
green while committing the reproduction, and — the useful part — `unittest`
reports an *unexpected success* as a failure. The day someone fixes the bug, the
suite tells them this test is now passing and the marker should come off. It's a
regression test that also announces its own resolution.

## What is and isn't testable here

Judge each issue on its own; don't take a verdict from a list. The question is
narrower than "can I run the user's setup" — it is **can I put the code into
the state where the defect occurs**. For a protocol client those come apart in
a specific, useful way: you cannot run the reporter's TigerVNC, QEMU or VMware,
but everything a server does to this client arrives as bytes, and bytes are
replayable. The server is out of reach; its bytes are not.

The best threads hand you the trace. #90's black-capture report includes the
`-v` log showing exactly what arrived — a `PSEUDO_DESKTOP_SIZE` pseudo-rect,
then "Stopping factory" with no pixel data — which is a byte sequence you can
feed to `RFBClient` even though TightVNC-on-Windows is unreachable. A `vncdo -v`
log, a `vnclog` capture, or a quoted security-type list is a repro kit in
disguise. When the thread lacks one, asking for it (outcome C) is asking for
exactly the thing that converts the issue from B to A.

Usually unit-testable: RFB message parsing and handshake/auth negotiation
(`rfb.py`), key mapping and event ordering (`keys.py`, `keyPress`), CLI parsing
and command dispatch (`command.py`), capture/expect decision logic given
synthetic framebuffer data.

The functional tier (`tests/functional/`, run by CI) drives the real `vncdo`
against libvncserver's example server — `make libvnc-examples` builds it,
`make test-func` runs it, `pexpect` drives it. There is also a docker-compose
fleet of real servers (TigerVNC, UltraVNC and others) under `tests/servers/`,
driven by `tests/servers/servers.mk` (`servers-up` / `test-servers`) — check
whether the reporter's server is in that fleet before concluding it is out of
reach. Both exist for whole-client-loop behaviour against specific servers:
prefer the unit tier, and don't mistake "passes against libvncserver" for
"fixed against the reporter's server" unless the fleet actually ran the
reporter's server.

Genuinely out of reach — outcome B — is behaviour that lives in the third-party
server or the environment itself: whether TigerVNC in shared mode ever sends
the update, real network timing and mid-session disconnects, a platform-specific
thread interaction, anything needing the reactor actually running. Here you
would have to mock the very thing that's broken, and the test would pass or
fail for reasons unrelated to the bug.

Before writing any of it, check the behaviour isn't intended. `docs/library.rst`
documents deliberate choices that look like defects from the outside — the
reactor surviving context-manager exit, and `api.shutdown()` being the caller's
job, are the notable ones. A test asserting documented behaviour pins the
design in place while claiming to be a bug report.

## Where the test lives, and where it goes

A per-issue file is the right shape for triage and the wrong shape for the
codebase. It buys something real while the issue is open — one file, obviously
disposable, named so anyone can connect it to the thread — but a `tests/unit/`
directory that accumulates `test_issue_90.py`, `test_issue_127.py` is a tree of
orphans organised by the one fact that stops mattering the moment the bug is
fixed.

So the file is explicitly a staging area, and the fix is what retires it. Pick
its permanent home when you write it, and say so in three places, because the
person who fixes this may never read this skill: the class docstring (the
`TRIAGE ARTIFACT` note above), the PR body, and the triage comment.

Homes, by what the test touches:

| Subject | Home |
|---|---|
| RFB wire protocol — handshake, auth/security types, encodings, server messages | `tests/unit/test_rfb.py` |
| `VNCDoToolClient` — key/mouse commands, capture and expect logic | `tests/unit/test_client.py` |
| `vncdo` CLI — argument parsing, command dispatch | `tests/unit/test_command.py` |
| `api.py` threaded wrapper, `loggingproxy.py` / `vnclog` | no unit file exists yet — say so in the PR |
| Whole-client behaviour needing a live (libvncserver) server | `tests/functional/` |

An empty cell in that table is information about the suite, not a defect in
your test — `api.py`'s thread-and-queue wrapper has no unit coverage today,
and a triage PR that says so plainly is worth more than one that buries a new
file without comment.

## Known harness limits

**`rfb.py` logs through Twisted, not stdlib logging.** The protocol layer uses
`twisted.python.log` (that's why reporters' logs say `INFO:twisted:...`), while
`client.py` and `api.py` use `logging.getLogger(__name__)`. So
`assertLogs('vncdotool')` sees nothing from the protocol layer — it reads as
"my repro never reached the code" when the assertion is just watching the wrong
logger. Assert on behaviour (calls, state, `loseConnection`) rather than on
protocol-layer log output.

**The framebuffer needs Pillow-decodable data.** Capture paths hand rectangle
bytes to Pillow; a synthetic framebuffer update has to be internally consistent
(pixel format, byte counts) or you get a decode error that looks like the bug
but isn't. Crib the message constants from `tests/unit/test_client.py`
(`MSG_HANDSHAKE`, `MSG_INIT`) rather than hand-rolling them.

## Before opening the PR

```
python -m unittest tests.unit.test_issue_NNN -v      # must report expected failure
python -m unittest discover tests/unit               # everything else still green
flake8 --count --statistics vncdotool tests          # CI-enforced lint
```

Lint is plain flake8, configured in `setup.cfg`: line length 127,
`extend-ignore = E203`. No black, no isort — match the file you're nearest to.
