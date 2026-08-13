"""Server-parameterized scenarios: the data + callable pair everything else drives.

`tests/functional/vncservers.py` describes *servers*; this module describes
*scenarios* -- the things we do against a server and the assertions that
follow. Splitting them out (rather than adding `test_mouse`, `test_expect`,
... as sibling methods on the existing test mixin) matters because the same
scenario list has to serve three consumers, only one of which is unittest:

1. **unittest** -- ``vncservers.register_server_tests()`` builds the servers
   x scenarios cross product, one ``test_<scenario>`` per server, so CI
   reports a pass/fail/skip grid.
2. **the recorder** -- the compatibility plan's `vncdo record` wrapper over
   `loggingproxy` drives a scenario against a server and writes a fixture
   directory. That only works if a scenario is callable outside a
   ``TestCase``.
3. **the Tier 3 checklist** -- the "short scripted scenario checklist" a
   community contributor runs by hand against a server we cannot host. It
   has to be printable/enumerable, i.e. data (name + description), not
   buried in test method bodies.

So a ``Scenario`` is a `NamedTuple` (data) wrapping a plain function (the
callable), and ``SCENARIOS`` is the ordered registry both unittest and the
future recorder consume.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Callable, FrozenSet, List, NamedTuple, Tuple

from PIL import Image

if TYPE_CHECKING:
    from vncdotool import api

    from .vncservers import VNCServer

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# getcolors() returns None above this many distinct colours, which is itself
# proof the capture isn't a flat colour, so the cap only needs to be cheap.
MAX_COLOURS = 256


# ---------------------------------------------------------------------------
# Assertion-level helpers
#
# Input scenarios (keyboard/mouse, PR 3b) assert at the strongest level the
# server's capabilities support. Each level raises plain ``AssertionError``
# rather than using ``self.assertX`` -- a ``Scenario.run`` body is a plain
# function, not a ``TestCase`` method, and unittest treats an
# ``AssertionError`` raised inside a generated test method as an ordinary
# failure either way.
# ---------------------------------------------------------------------------


def PROTOCOL(client: "api.ThreadedVNCClientProxy") -> None:
    """Weakest level, always available: the session is alive and answers.

    No capability required -- every server that connects at all supports
    this. Proves the connection survived whatever the scenario just did and
    that a framebuffer update still arrives; proves nothing about what that
    update contains.
    """
    client.refreshScreen()


def CHANGE(before: Image.Image, after: Image.Image) -> None:
    """The framebuffer differs at all between two captures.

    Enabled by ``renders_desktop``. Honest about its weakness: a repainting
    clock or a blinking cursor also changes the framebuffer, so this proves
    *some* repaint happened after the action, not that the action itself is
    what got rendered.
    """
    if before.tobytes() == after.tobytes():
        raise AssertionError(
            "framebuffer is byte-identical before and after the action -- "
            "CHANGE only proves some repaint occurred following the action, "
            "and here none did"
        )


def PIXEL(before: Image.Image, after: Image.Image, region: Tuple[int, int, int, int]) -> None:
    """A *specific region* changed between two captures.

    Enabled by ``input_reactive``. Unreachable today: no Tier 1 server
    declares ``input_reactive`` because ``tests/servers/draw-content.sh``
    paints static content, so nothing in the fleet reacts to input in a
    known region. See the "input-reactive test surface" follow-up in
    docs/server-compatibility-plan.md. This level is implemented now so
    that follow-up spike only has to flip a capability flag, not invent an
    assertion.
    """
    if before.crop(region).tobytes() == after.crop(region).tobytes():
        raise AssertionError(f"region {region} did not change after the action")


class ScenarioContext(NamedTuple):
    """What a scenario body gets besides the connected client.

    Bundled here rather than reached for as globals so a scenario body is a
    pure function of ``(client, ctx)`` -- the property that lets the
    recorder and the unittest generator share it.
    """

    server: "VNCServer"
    # Where this scenario, for this server, writes its artifacts:
    # screenshots/<server>/<scenario>/.
    artifact_dir: Path
    # The assertion-level helpers above, bundled for convenience so a
    # scenario body can write ``ctx.CHANGE(...)`` without a separate import.
    PROTOCOL: Callable = PROTOCOL
    CHANGE: Callable = CHANGE
    PIXEL: Callable = PIXEL


ScenarioRun = Callable[["api.ThreadedVNCClientProxy", ScenarioContext], None]


class Scenario(NamedTuple):
    # Used in test ids ("test_connect") and fixture dirs.
    name: str
    # One line, printed in the Tier 3 checklist.
    description: str
    # Capabilities (see VNCServer.capabilities) the server must declare for
    # this scenario to run at all; a server missing one skips rather than
    # runs a weakened version. Scenarios below whose assertions merely
    # *degrade* gracefully per-capability (capture) require nothing here --
    # the degrading is inside the scenario body instead.
    requires: FrozenSet[str]
    run: ScenarioRun


def _run_connect(client: "api.ThreadedVNCClientProxy", ctx: ScenarioContext) -> None:
    """Handshake completes; record what was negotiated.

    This is the seed of the ``vncdo probe`` output Phase 4 wants: which
    protocol version and security type a server actually speaks.
    """
    PROTOCOL(client)

    version = getattr(client, "_version", None)
    version_str = "%d.%d" % version if version else "unknown"
    report = (
        f"server: {ctx.server.name}\n"
        f"protocol_version: {version_str}\n"
        f"security_type: {ctx.server.auth_capability}\n"
    )
    (ctx.artifact_dir / "connect.txt").write_text(report)


def _run_capture(client: "api.ThreadedVNCClientProxy", ctx: ScenarioContext) -> None:
    """Capture the framebuffer to a PNG and check it.

    Always checked: the file is non-empty and starts with the PNG magic
    bytes. Checked when the server's capabilities allow it: the image size
    matches what the server is known to serve (``known_size``), and the
    capture is not a single flat colour (``renders_desktop`` -- a server
    with no rendered desktop, e.g. a hosted macOS runner, is expected to
    produce a flat framebuffer and is not treated as a failure for it).
    """
    server = ctx.server
    png = ctx.artifact_dir / "capture.png"
    client.captureScreen(str(png))

    data = png.read_bytes()
    if not data:
        raise AssertionError(f"{server.name}: captured screenshot is empty")
    if data[:8] != PNG_MAGIC:
        raise AssertionError(f"{server.name}: captured file is not a valid PNG")

    with Image.open(png) as image:
        if "known_size" in server.capabilities:
            if image.size != server.size:
                raise AssertionError(f"{server.name}: capture is not the size the server serves")
        colours = image.convert("RGB").getcolors(maxcolors=MAX_COLOURS)

    if "renders_desktop" not in server.capabilities:
        distinct = colours if colours is None else len(colours)
        print(
            f"{server.name}: {distinct} colours captured; content is not "
            "asserted, this server has no rendered desktop behind it"
        )
        return

    distinct = colours if colours is None else len(colours)
    if distinct == 1:
        raise AssertionError(f"{server.name}: capture is a single flat colour, no screen content was decoded")


# Order is stable and meaningful (connect first) because the recorder
# replays scenarios in order and the Tier 3 checklist prints them in order.
#
# Only connect/capture are here in this PR -- authenticate/keyboard/mouse/
# expect land in the follow-up PR once this abstraction has been reviewed
# with a small number of users rather than six at once.
SCENARIOS: List[Scenario] = [
    Scenario(
        name="connect",
        description="RFB handshake completes and a security type is negotiated",
        requires=frozenset(),
        run=_run_connect,
    ),
    Scenario(
        name="capture",
        description="framebuffer capture decodes to a valid PNG, sized and non-flat where the server allows",
        requires=frozenset(),
        run=_run_capture,
    ),
]
