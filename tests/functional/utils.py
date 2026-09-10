"""Shared description of the VNC servers vncdotool is tested against.

Two families of server are described here and driven by the same code:

* ``docker`` -- the Linux servers built and run by
  ``tests/servers/docker-compose.yml`` (see ``make servers-up``);
* ``os`` -- an OS-hosted server on the machine running the tests, i.e.
  UltraVNC on Windows, Apple Screen Sharing on macOS, or a raw QEMU on
  Linux, set up by the scripts under ``tests/servers/ultravnc``,
  ``tests/servers/screen-sharing``, and ``tests/servers/qemu-kvm``.

The two differ only in how the server is started and in what a capture is
allowed to contain, so everything else -- connecting, capturing, the
per-server test body, the screenshot gallery -- is shared rather than
written twice.
"""

import contextlib
import json
import os
import re
import select
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import (
    Any,
    Callable,
    ContextManager,
    Dict,
    Iterator,
    List,
    Mapping,
    NamedTuple,
    Optional,
    Sequence,
    Set,
    Tuple,
)
from unittest import TestCase

from PIL import Image, ImageChops

from vncdotool import api

HOST = "127.0.0.1"
CONNECT_TIMEOUT = 5.0
PORT_PROBE_TIMEOUT = 1.0
RETRY_DELAY = 2.0
# Readiness budget for wait_until_ready(): how long one connection attempt
# is given before it is abandoned, and how long to keep making them.
READY_ATTEMPT_TIMEOUT = 20.0
READY_DEADLINE = 180.0

# Named by full path rather than resolved through PATH: another working tree's
# .venv can come first there, and the suite would report its behaviour as this
# branch's.
_SCRIPTS = Path(sys.executable).parent
_EXE_SUFFIX = ".exe" if os.name == "nt" else ""
VNCDO = str(_SCRIPTS / f"vncdo{_EXE_SUFFIX}")
VNCDO_REPLAY = str(_SCRIPTS / f"vncdo-replay{_EXE_SUFFIX}")
VNCLOG = str(_SCRIPTS / f"vnclog{_EXE_SUFFIX}")
# Added to the server's response budget for interpreter start-up and handshake.
SUBPROCESS_TIMEOUT_HEADROOM = 10.0
VNCLOG_STARTUP_DEADLINE = 10.0
VNCLOG_CAPTURE_DEADLINE = 60.0

DEFAULT_SCREENSHOT_DIR = Path(__file__).resolve().parents[1] / "servers" / "screenshots"

# `name:` in tests/servers/docker-compose.yml, and so the prefix compose
# gives every container it starts from that file.
FLEET_PROJECT = "vncdo-test-servers"
FLEET_TAG_SCRIPT = Path(__file__).resolve().parents[1] / "servers" / "fleet-tag.sh"
FLEET_PROBE_TIMEOUT = 30.0

# Two pointer positions a capture is compared at, and a box comfortably
# larger than the biggest cursor the fleet sends (libvncserver's 32x32). A
# shape is drawn at the pointer minus its hotspot, so it reaches above and
# left of the position as well as below and right.
CURSOR_NEAR = (20, 20)
CURSOR_FAR = (150, 120)
CURSOR_EXTENT = 48

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# getcolors() returns None above this many distinct colours, which is itself
# proof the capture isn't a flat colour, so the cap only needs to be cheap.
MAX_COLOURS = 256


class VNCServer(NamedTuple):
    name: str
    port: int
    password: Optional[str] = None
    # Username, for servers whose security type authenticates one (Apple's
    # ARD/Diffie-Hellman); None selects VNC password auth or no auth.
    username: Optional[str] = None
    # Screen size the server is known to serve, so a capture can be checked
    # against it; None where the size is whatever the host display happens
    # to be and therefore can't be asserted.
    size: Optional[Tuple[int, int]] = (1024, 768)
    # False means a flat, usually all-black, framebuffer is expected rather
    # than a failure -- see the macOS note in tests/servers/screen-sharing.
    renders_desktop: bool = True
    # True where a pointer event ends the session instead of being acted on,
    # so a grid that drives one has to leave this server out.
    skip_pointer_tests: bool = False
    # The default suits a container on loopback; an OS-hosted server sharing
    # a busy machine's real desktop can be far slower.
    timeout: float = CONNECT_TIMEOUT
    address: Optional[str] = None
    extra_args: Tuple[str, ...] = ()
    # How to get this server running, quoted when a test fails because it is down.
    how_to_start: str = "start the servers first with `make servers-up`"
    # Honoured only off CI -- see absent_server_skips().
    skip_when_down: bool = False
    normalize_size_keys: Tuple[str, ...] = ()
    # A CA to trust, for a server whose address takes no --tls-ca-cert.
    # OpenSSL reads one from SSL_CERT_FILE instead.
    tls_ca: Optional[Path] = None
    # Held open around anything that talks to this server, where its address
    # resolves only inside a session.
    session: Optional[Callable[[], ContextManager[None]]] = None
    # False on a server whose framebuffer never had a pointer in it --
    # qemu's text-mode boot screen, a headless Xvnc -- where no shape is the
    # right answer.
    has_pointer: bool = False


# Both written by their container into a bind mount at every start; neither
# exists until the fleet has run.
VENCRYPT_CA_CERT = (
    Path(__file__).resolve().parents[1] / "servers" / "vencrypt-certs" / "cert.pem"
)
WAYVNC_CA_CERT = (
    Path(__file__).resolve().parents[1] / "servers" / "wayvnc-certs" / "cert.pem"
)

# One constant per service in tests/servers/docker-compose.yml, named so a
# test that needs a specific one can import it directly instead of
# searching TCP_SERVERS by name.
TIGERVNC = VNCServer("tigervnc", 5931, size=(256, 192))
TIGERVNC_AUTH = VNCServer("tigervnc-auth", 5932, password="vncdotool")
X11VNC = VNCServer("x11vnc", 5933, size=(256, 192), has_pointer=True)
TIGERVNC_VENCRYPT = VNCServer(
    "tigervnc-vencrypt", 5941, password="vncdotool", size=(256, 192),
    extra_args=("--tls-ca-cert", str(VENCRYPT_CA_CERT)),
)
TIGERVNC_VENCRYPT_ANON = VNCServer(
    "tigervnc-vencrypt-anon", 5951, password="vncdotool", size=(256, 192),
    extra_args=("--tls-insecure-skip-verify",),
)
WAYVNC = VNCServer(
    "wayvnc", 5952, username="vncdotool", password="vncdotool", size=(256, 192),
    extra_args=("--tls-ca-cert", str(WAYVNC_CA_CERT)),
)
# 800x600 is the size the demo starts at; it takes no -geometry option, and
# any client's arrow keys resize it for every later client.
LIBVNCSERVER_EXAMPLE = VNCServer(
    "libvncserver-example", 5935, size=(800, 600),
    normalize_size_keys=("up", "up", "down"),
    has_pointer=True,
)

TCP_SERVERS = [
    TIGERVNC,
    TIGERVNC_AUTH,
    TIGERVNC_VENCRYPT,
    TIGERVNC_VENCRYPT_ANON,
    WAYVNC,
    X11VNC,
    LIBVNCSERVER_EXAMPLE,
]

# The servers running tests/goldens/scene_player.py, so a test can ask them
# to display a committed PNG. SELENOID and KASMVNC are appended below, once
# their addresses are defined.
SCENE_SERVERS = [TIGERVNC, X11VNC, WAYVNC]

TLS_OPTIONS = ("--tls-ca-cert", "--tls-insecure-skip-verify")


def vnclog_can_reach(server: VNCServer) -> bool:
    """vnclog takes neither a TLS option nor a ws:// address.

    An `address` server is behind a WebSocket bridge, so its port speaks
    HTTP rather than RFB and dialling it as `HOST::port` hangs.
    """
    if server.address is not None:
        return False
    return not any(option in server.extra_args for option in TLS_OPTIONS)


# QEMU presents a leaf signed by a CA rather than a self-signed certificate,
# so the trust anchor cannot be read off the connection. Its service writes
# the CA here at start-up.
QEMU_TLS_CA = Path(__file__).resolve().parent.parent / "servers" / "qemu-tls" / "ca-cert.pem"

# 1280x800 is the mode OVMF's UEFI shell settles in.
QEMU = VNCServer("qemu", 5944, size=(1280, 800), address="ws://127.0.0.1:5944/")
QEMU_TLS = VNCServer(
    "qemu-tls", 5945, size=(1280, 800), address="wss://localhost:5945/",
    tls_ca=QEMU_TLS_CA,
)


@contextlib.contextmanager
def selenoid_session() -> Iterator[None]:
    endpoint = f"http://{HOST}:{SELENOID.port}/wd/hub/session"
    body = json.dumps(
        {
            "capabilities": {
                "alwaysMatch": {
                    "browserName": "stub",
                    "browserVersion": "1.0",
                    "selenoid:options": {"enableVNC": True},
                }
            }
        }
    ).encode()
    request = urllib.request.Request(
        endpoint, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=SELENOID.timeout) as response:
        session_id = json.loads(response.read())["sessionId"]
    try:
        yield
    finally:
        urllib.request.urlopen(
            urllib.request.Request(f"{endpoint}/{session_id}", method="DELETE"),
            timeout=SELENOID.timeout,
        ).close()


# Selenoid keys the session off the URL path, so this address only resolves
# while a WebDriver session with this id is open.
SELENOID_SESSION_ID = "c2ec57a377e94f515b35b2a57caad26e"
SELENOID = VNCServer(
    "selenoid", 5946, size=(256, 192),
    address=f"ws://127.0.0.1:5946/vnc/{SELENOID_SESSION_ID}?password=vncdotool",
    session=selenoid_session,
)

KASMVNC = VNCServer(
    "kasmvnc", 5947, size=(256, 192),
    address="ws://127.0.0.1:5947/?password=vncdotool",
    skip_pointer_tests=True,
)

WEBSOCKET_SERVERS = [QEMU, QEMU_TLS, SELENOID, KASMVNC]

# Both run the scene player behind their bridge, so the encoding and pixel
# format grids reach them over ws:// and the handshake is exercised by every
# case rather than by a test of its own.
SCENE_SERVERS += [SELENOID, KASMVNC]

SUPPORTED_SERVERS = [
    TIGERVNC,
    X11VNC,
    WAYVNC,
    LIBVNCSERVER_EXAMPLE,
    QEMU,
    SELENOID,
]


# An event sink rather than a rendering server, so it stays out of the smoke
# grid; test_events.py still needs its host/port.
VNCEV = VNCServer("vncev", 5934, renders_desktop=False, size=None)

# Credentials the OS-hosted server setup scripts configure. They are spike
# credentials for a throwaway runner, deliberately visible; a permanent job
# passes real ones through these environment variables from CI secrets.
OS_SERVER_USERNAME = os.environ.get("VNCDOTOOL_OS_SERVER_USERNAME", "vncspike")
OS_SERVER_PASSWORD = os.environ.get("VNCDOTOOL_OS_SERVER_PASSWORD", "vncspike1")
OS_SERVER_PORT = int(os.environ.get("VNCDOTOOL_OS_SERVER_PORT", "5900"))
# An OS-hosted server shares a real, sometimes busy, desktop session, and
# answers input events a lot less promptly than a container does: macOS
# Screen Sharing took over five seconds to acknowledge a key event.
OS_SERVER_TIMEOUT = float(os.environ.get("VNCDOTOOL_OS_SERVER_TIMEOUT", "60"))


def os_server(name: str, how_to_start: str, **overrides: Any) -> VNCServer:
    # size=None throughout: an OS-hosted server serves whatever the host
    # display or the firmware left behind, never a geometry we configure.
    overrides.setdefault("port", OS_SERVER_PORT)
    return VNCServer(
        name=name,
        size=None,
        timeout=OS_SERVER_TIMEOUT,
        how_to_start=how_to_start,
        skip_when_down=True,
        **overrides,
    )


# Each server's setup.ps1 configures the same port number.
ULTRAVNC = os_server(
    "ultravnc",
    "the OS server setup runs in CI only, see tests/servers/ultravnc/README.md",
    password=OS_SERVER_PASSWORD,
    has_pointer=True,
)

TIGHTVNC = os_server(
    "tightvnc",
    "the OS server setup runs in CI only, see tests/servers/tightvnc/README.md",
    port=5901,
    password=OS_SERVER_PASSWORD,
    has_pointer=True,
)

TIGERVNC_WIN = os_server(
    "tigervnc-win",
    "the OS server setup runs in CI only, see tests/servers/tigervnc-win/README.md",
    port=5902,
    password=OS_SERVER_PASSWORD,
    has_pointer=True,
)

SCREEN_SHARING = os_server(
    "screen-sharing",
    "the OS server setup runs in CI only, see tests/servers/screen-sharing/README.md",
    password=OS_SERVER_PASSWORD,
    # macOS Screen Sharing authenticates a local user over ARD/DH; the
    # legacy VNC-password path is silently accepted but non-functional on
    # current macOS.
    username=OS_SERVER_USERNAME,
    # A hosted macOS runner has no rendered desktop session behind the
    # framebuffer, so captures come back black even though the protocol,
    # auth and input round trip all succeeded.
    renders_desktop=False,
)

QEMU_KVM = os_server(
    "qemu-kvm",
    "set the server up first with tests/servers/qemu-kvm/setup.sh",
)

# Set by tests/servers/qemu-kvm/setup.sh, the only thing that starts this
# server; other jobs share the Linux runners with it and never do.
QEMU_KVM_OPT_IN = "VNCDOTOOL_OS_SERVER_LINUX"

OS_SERVERS_BY_PLATFORM: Dict[str, List[VNCServer]] = {
    "win32": [ULTRAVNC, TIGHTVNC, TIGERVNC_WIN],
    "darwin": [SCREEN_SHARING],
    "linux": [QEMU_KVM] if os.environ.get(QEMU_KVM_OPT_IN) else [],
}


def os_servers(platform: str = sys.platform) -> List[VNCServer]:
    return OS_SERVERS_BY_PLATFORM.get(platform, [])


def select_servers(group: str) -> List[VNCServer]:
    groups = {"docker": TCP_SERVERS + WEBSOCKET_SERVERS, "os": os_servers()}
    if group == "all":
        return [server for servers in groups.values() for server in servers]
    if group not in groups:
        raise ValueError(f"unknown server group {group!r}, expected one of {sorted(groups)} or 'all'")
    return groups[group]


CI_ENV_VARS = ("CI", "GITHUB_ACTIONS")
NOT_CI_VALUES = ("", "0", "false", "no")


def running_in_ci(env: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    return any(env.get(name, "").strip().lower() not in NOT_CI_VALUES for name in CI_ENV_VARS)


def absent_server_skips(server: VNCServer, env: Optional[Mapping[str, str]] = None) -> bool:
    return server.skip_when_down and not running_in_ci(env)


def fleet_tag() -> Optional[str]:
    """The tag this checkout's fleet images are built under, or None.

    fleet-tag.sh reads the git object store, so a tree unpacked without
    one has no tag to give.
    """
    try:
        result = subprocess.run(
            [str(FLEET_TAG_SCRIPT)], capture_output=True, text=True, timeout=FLEET_PROBE_TIMEOUT
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


def running_fleet_tag(server: VNCServer) -> Optional[str]:
    """The tag of the image `server`'s container was started from, or None."""
    container = f"{FLEET_PROJECT}-{server.name}-1"
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.Config.Image}}", container],
            capture_output=True,
            text=True,
            timeout=FLEET_PROBE_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    _, _, tag = result.stdout.strip().rpartition(":")
    return tag or None


_FLEET_MISMATCHES: Dict[str, Optional[str]] = {}


def fleet_mismatch(server: VNCServer) -> Optional[str]:
    """Why `server` is not this checkout's fleet, or None if it is or may be.

    Answered once per server and remembered: a grid of a hundred cases asks
    the same question a hundred times, and each answer costs two
    subprocesses.
    """
    if server.name in _FLEET_MISMATCHES:
        return _FLEET_MISMATCHES[server.name]

    expected, running = fleet_tag(), running_fleet_tag(server)
    if expected is None or running is None or expected == running:
        mismatch = None
    else:
        mismatch = (
            f"{server.name} is running image tag {running!r}, but this checkout's server sources "
            f"hash to {expected!r}: the fleet was started from a different checkout and serves "
            f"that checkout's files. Run `make servers-down && make servers-up`."
        )
    _FLEET_MISMATCHES[server.name] = mismatch
    return mismatch


def assert_fleet_current(server: VNCServer) -> None:
    mismatch = fleet_mismatch(server)
    if mismatch is not None:
        raise AssertionError(mismatch)


def screenshot_dir() -> Path:
    path = Path(os.environ.get("VNCDOTOOL_SCREENSHOT_DIR", DEFAULT_SCREENSHOT_DIR))
    path.mkdir(parents=True, exist_ok=True)
    return path


def port_open(host: str, port: int, timeout: float = PORT_PROBE_TIMEOUT) -> bool:
    """Cheap liveness check, not readiness -- see wait_until_ready()."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


SCENES_DIR = Path(__file__).resolve().parents[1] / "goldens" / "scenes"


def awaiting(key: str) -> Tuple[str, ...]:
    """`vncdo` arguments that block until the scene `key` selects is on screen.

    No fuzz argument: `expect` then derives one from the negotiated pixel
    format, and an explicit 0 would never come true at a reduced depth.
    """
    return ("expect", str(SCENES_DIR / f"{key}.png"))


_SEEN_UP: Set[Tuple[str, int]] = set()


def server_is_up(server: VNCServer) -> bool:
    """port_open() for a test's setUp, remembered for the rest of the process.

    Xvnc counts every connection closed before a successful authentication
    towards BlacklistThreshold, and a probe drops one without ever speaking
    RFB. One per test in a grid of a hundred blacklists the harness itself.
    """
    key = (HOST, server.port)
    if key in _SEEN_UP:
        return True
    if port_open(HOST, server.port):
        _SEEN_UP.add(key)
        return True
    return False


class FleetTestCase(TestCase):
    """Base for a grid that runs one body against several fleet servers."""

    server: VNCServer

    @classmethod
    def setUpClass(cls) -> None:
        assert_fleet_current(cls.server)

    def setUp(self) -> None:
        if not server_is_up(self.server):
            self.fail(
                f"{self.server.name} is not listening on {self.server.port}; "
                f"{self.server.how_to_start}"
            )
        if self.server.session is not None:
            session = self.server.session()
            session.__enter__()
            self.addCleanup(session.__exit__, None, None, None)


def connect(server: VNCServer, timeout: Optional[float] = None) -> api.ThreadedVNCClientProxy:
    """Connect to one server, with whatever credentials its security type needs.

    Remember that the returned client is a context manager, and that
    ``api.shutdown()`` still has to be called once before the process exits.
    And that shutdown is terminal for the whole process: after it, no
    further ``connect()`` can ever work again (the reactor cannot restart),
    which is why only ONE test module -- test_api_lifecycle.py -- may use
    this in-process; everything else shells out via run_vncdo().
    """
    client = api.connect(
        f"{HOST}::{server.port}",
        password=server.password,
        username=server.username,
    )
    client.timeout = server.timeout if timeout is None else timeout
    return client


@contextlib.contextmanager
def probe_context(server: VNCServer) -> Iterator[Optional[Dict[str, str]]]:
    """What a bare `vncdo capture` of this server needs around it."""
    env = {"SSL_CERT_FILE": str(server.tls_ca)} if server.tls_ca else None
    if server.session is None:
        yield env
    else:
        with server.session():
            yield env


def capture_screenshot(
    server: VNCServer,
    path: Path,
    timeout: Optional[float] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Path:
    """Capture through the CLI, which is what carries a server's extra_args."""
    result = run_vncdo(server, "capture", str(path), timeout=timeout, env=env)
    if result.returncode != 0:
        raise AssertionError(
            f"{server.name}: vncdo capture exited {result.returncode}, "
            f"stderr:\n{result.stderr}"
        )
    return path


def distinct_colours(image: Image.Image) -> Optional[int]:
    colours = image.convert("RGB").getcolors(maxcolors=MAX_COLOURS)
    return colours if colours is None else len(colours)


def has_expected_content(server: VNCServer, colours: Optional[int]) -> bool:
    if not server.renders_desktop:
        return True
    return colours != 1


# A desktop that has not finished painting is almost entirely one colour but
# not entirely, so counting colours does not catch it. UltraVNC's first
# capture after connecting came back 99% black with 700 colours in it.
BLANK_FRACTION = 0.95


def blank_fraction(image: Image.Image) -> float:
    """How much of `image` is its single commonest colour."""
    colours = image.convert("RGB").getcolors(maxcolors=image.width * image.height)
    if not colours:
        return 0.0
    return max(count for count, _ in colours) / (image.width * image.height)


def normalize_size(server: VNCServer) -> None:
    """Put a server whose size a client can change back to ``server.size``."""
    if not server.normalize_size_keys:
        return
    argv = [arg for key in server.normalize_size_keys for arg in ("key", key)]
    result = run_vncdo(server, *argv)
    if result.returncode != 0:
        raise RuntimeError(
            f"{server.name}: `vncdo {' '.join(argv)}` exited {result.returncode}, "
            f"stderr:\n{result.stderr}"
        )


def wait_until_ready(
    server: VNCServer,
    deadline_seconds: float = READY_DEADLINE,
    attempt_timeout: float = READY_ATTEMPT_TIMEOUT,
) -> bool:
    """Block until ``server`` serves the screen the tests expect, or give up.

    Servers accept connections before they have anything to show, so
    readiness has to be a capture. The whole connection is retried because
    macOS Screen Sharing is socket-activated: the first connection starts
    it and can stall indefinitely while the next succeeds at once.
    """
    deadline = time.monotonic() + deadline_seconds
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        if not port_open(HOST, server.port):
            time.sleep(RETRY_DELAY)
            continue
        try:
            normalize_size(server)
            with probe_context(server) as env, tempfile.TemporaryDirectory() as tmp:
                probe = Path(tmp) / f"{server.name}-ready.png"
                capture_screenshot(server, probe, timeout=attempt_timeout, env=env)
                with Image.open(probe) as image:
                    colours = distinct_colours(image)
                    size = image.size
        except Exception as exc:  # noqa: BLE001 - any failure means try again
            print(f"{server.name}: not ready yet (attempt {attempt}: {exc})")
            time.sleep(RETRY_DELAY)
            continue
        if not has_expected_content(server, colours):
            print(f"{server.name}: not ready yet (attempt {attempt}: capture is flat)")
            time.sleep(RETRY_DELAY)
            continue
        if server.size is not None and size != server.size:
            print(f"{server.name}: not ready yet (attempt {attempt}: serving {size}, expected {server.size})")
            time.sleep(RETRY_DELAY)
            continue
        print(f"{server.name}: ready after {attempt} attempt(s)")
        return True

    print(f"{server.name}: never served the content it is expected to render")
    return False


def assert_cli_installed() -> None:
    missing = [script for script in (VNCDO, VNCDO_REPLAY, VNCLOG) if not Path(script).exists()]
    if missing:
        raise AssertionError(
            f"{', '.join(missing)} missing. These are console_scripts entry points: run "
            "`uv sync` in this working tree, or `pip install -e .` into the environment "
            "running these tests."
        )


assert_cli_installed()


def vncdo_argv(server: VNCServer, *args: str, options: Sequence[str] = ()) -> List[str]:
    argv = [VNCDO, "-s", server.address or f"{HOST}::{server.port}"]
    if server.password is not None:
        argv += ["-p", server.password]
    if server.username is not None:
        argv += ["-u", server.username]
    argv.extend(options)
    argv.extend(server.extra_args)
    argv.extend(args)
    return argv


def run_vncdo(
    server: VNCServer,
    *args: str,
    timeout: Optional[float] = None,
    env: Optional[Mapping[str, str]] = None,
    options: Sequence[str] = (),
) -> subprocess.CompletedProcess:
    """Run the real `vncdo` CLI against `server` and return the completed process.

    Never api.connect(): a hang is then contained by the kernel reaping the
    subprocess at `timeout`, not by anything in-process.
    """
    argv = vncdo_argv(server, *args, options=options)
    budget = (server.timeout if timeout is None else timeout) + SUBPROCESS_TIMEOUT_HEADROOM
    child_env = None if env is None else {**os.environ, **env}
    try:
        # stdin closed so an unexpected getpass() prompt fails instead of blocking.
        return subprocess.run(
            argv, capture_output=True, text=True, timeout=budget,
            stdin=subprocess.DEVNULL, env=child_env,
        )
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"{server.name}: `{' '.join(argv)}` did not finish within {budget}s"
        ) from exc


class Capture(NamedTuple):
    s2c: bytes
    meta: Dict[str, Any]


def capture_through_vnclog(
    testcase: TestCase, server: VNCServer, port: int, *args: str
) -> Capture:
    """Run `vncdo *args` against `server` through a vnclog proxy on `port`."""
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "capture.zip"
        proxy = subprocess.Popen(
            [VNCLOG, "-s", f"{HOST}::{server.port}", "--listen", str(port),
             "--capture-raw", str(archive)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True,
        )
        with proxy.stdout, proxy.stderr:
            deadline = time.monotonic() + VNCLOG_STARTUP_DEADLINE
            ready = False
            while time.monotonic() < deadline and not ready:
                if proxy.poll() is not None:
                    break
                rlist, _, _ = select.select([proxy.stderr], [], [], 0.2)
                if rlist and "accepting connections" in proxy.stderr.readline():
                    ready = True
            if not ready:
                proxy.kill()
                proxy.wait(timeout=VNCLOG_STARTUP_DEADLINE)
                testcase.fail(f"vnclog never listened on {port}")

            result = run_vncdo(server._replace(port=port), *args)
            proxy.wait(timeout=VNCLOG_CAPTURE_DEADLINE)

        if result.returncode != 0:
            testcase.fail(f"`vncdo {' '.join(args)}` through vnclog failed: {result.stderr}")

        with zipfile.ZipFile(archive) as zipped:
            return Capture(zipped.read("s2c.bin"), json.loads(zipped.read("meta.json")))


def _terminate(process: subprocess.Popen, timeout: float = 5.0) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)


def start_replay_server(
    testcase: TestCase, archive: Path, port: int, deadline: float = 10.0
) -> subprocess.Popen:
    """Start `vncdo-replay --server ARCHIVE --listen PORT --forever`, cleanup registered.

    Fails fast, with its stderr, if the process exits before listening."""
    server = subprocess.Popen(
        [VNCDO_REPLAY, "--server", str(archive), "--listen", str(port), "--forever"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
    )
    # Not kill(): Twisted's SIGTERM handler stops the reactor, so the
    # process exits through atexit and flushes what it still owes.
    testcase.addCleanup(_terminate, server)
    testcase.addCleanup(server.stdout.close)
    testcase.addCleanup(server.stderr.close)

    deadline_at = time.monotonic() + deadline
    while time.monotonic() < deadline_at:
        if server.poll() is not None:
            testcase.fail(f"vncdo-replay --server exited before listening; stderr:\n{server.stderr.read()}")
        if port_open(HOST, port):
            return server
        time.sleep(0.2)
    server.kill()
    testcase.fail(f"vncdo-replay --server never listened on {port}: {server.communicate()[1]}")


class _VNCServerTestMixin:
    """Shared test body, parameterized per-server by register_server_tests().

    Deliberately does NOT subclass TestCase, or `unittest discover` would
    also collect this shared base as its own, serverless test case.
    """

    server: VNCServer

    def setUp(self) -> None:
        if not server_is_up(self.server):
            unreachable = (
                f"{self.server.name} not reachable on {HOST}:{self.server.port} -- "
                f"{self.server.how_to_start}"
            )
            if absent_server_skips(self.server):
                self.skipTest(unreachable)
            self.fail(unreachable)
        if self.server is SELENOID:
            session = selenoid_session()
            session.__enter__()
            self.addCleanup(session.__exit__, None, None, None)

    def run_vncdo_ok(self, *args: str, options: Sequence[str] = ()) -> subprocess.CompletedProcess:
        result = run_vncdo(self.server, *args, options=options)
        self.assertEqual(
            result.returncode,
            0,
            f"{self.server.name}: `vncdo {' '.join(args)}` exited "
            f"{result.returncode}, stderr:\n{result.stderr}",
        )
        return result

    def assert_survives(self, *args: str) -> None:
        """vncdo sends the event and returns before the server reacts, so a
        zero exit status does not show the session survived it.
        """
        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / "after-input.png"
            self.run_vncdo_ok(*args, "pause", "0.3", "capture", str(png))

    def test_connect(self) -> None:
        """Handshake and auth succeed: `pause 0` still needs a live connection."""
        self.run_vncdo_ok("pause", "0")

    def test_keypress(self) -> None:
        """A key event is accepted and the session survives it."""
        self.assert_survives("key", "x")

    def test_mousemove(self) -> None:
        """A pointer event is accepted and the session survives it."""
        self.assert_survives("move", "10", "10")

    def test_click(self) -> None:
        """A button event is accepted and the session survives it."""
        self.assert_survives("move", "10", "10", "click", "1")

    def test_capture(self) -> None:
        """A framebuffer update is received and encoded to a PNG.

        A flat colour means no content was decoded, so it fails for any
        server with a desktop rendered behind it.
        """
        png = screenshot_dir() / f"{self.server.name}.png"

        self.run_vncdo_ok("capture", str(png))

        data = png.read_bytes()
        print(f"{self.server.name}: screenshot written to {png}")

        self.assertTrue(data, f"{self.server.name}: captured screenshot is empty")
        self.assertEqual(
            data[:8],
            PNG_MAGIC,
            f"{self.server.name}: captured file is not a valid PNG",
        )

        with Image.open(png) as image:
            if self.server.size is not None:
                self.assertEqual(
                    image.size,
                    self.server.size,
                    f"{self.server.name}: capture is not the size the server serves",
                )
            distinct = distinct_colours(image)

        if not self.server.renders_desktop:
            print(
                f"{self.server.name}: {distinct} colours captured; content is not "
                "asserted, this server has no rendered desktop behind it"
            )
            return

        self.assertTrue(
            has_expected_content(self.server, distinct),
            f"{self.server.name}: capture is a single flat colour, "
            "no screen content was decoded",
        )

    def capture_at_pointer(self, label: str, position: Tuple[int, int]) -> Image.Image:
        """Park the pointer at `position`, capture, and keep the wire log.

        `-v -v` names the encoding and geometry of every rectangle the server
        sends, which is the only way to tell a server that stopped painting
        the pointer from one that never had one.
        """
        x, y = position
        stem = screenshot_dir() / f"{self.server.name}-cursor-{label}"
        png = stem.with_suffix(".png")
        log = stem.with_suffix(".wire.log")
        log.unlink(missing_ok=True)
        self.run_vncdo_ok(
            "stable", "1", "move", str(x), str(y), "pause", "0.5", "capture", str(png),
            options=("-v", "-v", "--logfile", str(log)),
        )
        with Image.open(png) as image:
            capture = image.convert("RGB").copy()

        # Only where a pointer could be painted: qemu's UEFI shell is 99% one
        # colour by nature, and has no pointer for a blank capture to hide.
        if self.server.has_pointer:
            blank = blank_fraction(capture)
            self.assertLess(
                blank, BLANK_FRACTION,
                f"{self.server.name}: the {label} capture is {blank:.0%} one colour, "
                "so the desktop had not painted yet and nothing about the pointer "
                f"can be read off it. See {png}.",
            )
        return capture

    def warm_up_capture(self) -> None:
        """Connect and capture once, discarding it.

        UltraVNC's first capture after the service starts comes back before
        the desktop has painted, and an unpainted capture compared against a
        painted one differs everywhere.
        """
        run_vncdo(
            self.server, "capture", str(screenshot_dir() / f"{self.server.name}-warmup.png")
        )

    def test_capture_does_not_depend_on_where_the_pointer_is(self) -> None:
        """Neither pointer position leaves a mark on a capture.

        Only the neighbourhood of each position is compared, so a clock or a
        blinking cursor elsewhere on the screen cannot be read as a painted
        pointer. See specs/cursor.md.
        """
        self.warm_up_capture()
        # Twice at the same position before the one that moves: whatever
        # differs between these two is the desktop moving on its own, and a
        # region that will not hold still cannot answer the question.
        control = self.capture_at_pointer("control", CURSOR_NEAR)
        shots = {
            label: self.capture_at_pointer(label, position)
            for label, position in (("near", CURSOR_NEAR), ("far", CURSOR_FAR))
        }

        for label, position in (("near", CURSOR_NEAR), ("far", CURSOR_FAR)):
            box = cursor_box(position, shots["near"].size)
            drift = ImageChops.difference(
                control.crop(box), shots["near"].crop(box)
            ).getbbox()
            self.assertIsNone(
                drift,
                f"{self.server.name}: the {label} region {box} changed between two "
                f"captures taken at the same pointer position (region {drift}), so "
                "the desktop is animating there and nothing about the pointer can "
                "be read off it.",
            )

            difference = ImageChops.difference(
                shots["near"].crop(box), shots["far"].crop(box)
            )
            self.assertIsNone(
                difference.getbbox(),
                f"{self.server.name}: the capture changed around the {label} "
                f"pointer position {position} (region {box}) when the pointer "
                f"moved between {CURSOR_NEAR} and {CURSOR_FAR}, and did not change "
                "with the pointer parked. The server is painting it into the "
                "framebuffer despite being offered Cursor.",
            )


class Rectangle(NamedTuple):
    encoding: str
    width: int
    height: int
    x: int
    y: int


# rfb.py logs one of these per rectangle at DEBUG, through const._named:
# `Received PSEUDO_CURSOR (-239) rectangle 32x32+0+0`, with the number in hex
# above the vendor blocks and `unknown` for a name vncdotool has none for.
_RECTANGLE_LOG = re.compile(
    r"Received (?P<name>\w+) \(-?(?:0x)?[0-9a-f]+\) "
    r"rectangle (?P<w>\d+)x(?P<h>\d+)\+(?P<x>\d+)\+(?P<y>\d+)"
)


def parse_wire_log(path: Path) -> List[Rectangle]:
    """Every framebuffer rectangle `vncdo -v -v` recorded, in arrival order."""
    if not path.exists():
        return []
    return [
        Rectangle(
            encoding=match["name"],
            width=int(match["w"]), height=int(match["h"]),
            x=int(match["x"]), y=int(match["y"]),
        )
        for match in _RECTANGLE_LOG.finditer(path.read_text(errors="replace"))
    ]


class CursorShapeOffered:
    """Deliberately not a TestCase: discovery would collect the shared base itself."""

    server: VNCServer

    def test_offering_cursor_yields_a_shape_that_can_be_drawn(self) -> None:
        """A server with a pointer answers -239 with a shape `--localcursor` can paint.

        A 0x0 rectangle does not count, nor does no rectangle at all: either
        way there is nothing for the client to draw.
        """
        log = screenshot_dir() / f"{self.server.name}-cursor-shape.wire.log"
        log.unlink(missing_ok=True)
        png = screenshot_dir() / f"{self.server.name}-cursor-shape.png"
        result = run_vncdo(
            self.server,
            "move", str(CURSOR_NEAR[0]), str(CURSOR_NEAR[1]),
            "pause", "0.5", "capture", str(png),
            options=("-v", "-v", "--logfile", str(log)),
        )
        self.assertEqual(
            result.returncode, 0,
            f"{self.server.name}: the wire probe exited {result.returncode}, "
            f"stderr:\n{result.stderr}",
        )

        rectangles = parse_wire_log(log)
        self.assertTrue(rectangles, f"{self.server.name}: no rectangles logged to {log}")

        cursors = [r for r in rectangles if r.encoding == "PSEUDO_CURSOR"]
        summary = ", ".join(f"{r.width}x{r.height}" for r in cursors) or "none"
        self.assertTrue(
            [r for r in cursors if r.width and r.height],
            f"{self.server.name}: offering Cursor (-239) got back no shape with a "
            f"non-zero size (cursor rectangles: {summary}). The pointer cannot be "
            "drawn locally, so --localcursor has nothing to paint.",
        )


def cursor_box(position: Tuple[int, int], size: Tuple[int, int]) -> Tuple[int, int, int, int]:
    """A box big enough for any cursor drawn at `position`, clipped to `size`."""
    x, y = position
    width, height = size
    return (
        max(0, x - CURSOR_EXTENT), max(0, y - CURSOR_EXTENT),
        min(width, x + CURSOR_EXTENT), min(height, y + CURSOR_EXTENT),
    )


def register_server_tests(
    servers: List[VNCServer], namespace: Dict[str, object], base: type = TestCase
) -> None:
    """Add one TestCase subclass per server to a test module's namespace.

    Gives `unittest discover` a separate pass/fail/skip per server instead of
    one test that stops at the first server that misbehaves.
    """
    for server in servers:
        name = "TestServer_" + server.name.replace("-", "_")
        bases: Tuple[type, ...] = (_VNCServerTestMixin, base)
        if server.has_pointer:
            bases = (CursorShapeOffered,) + bases
        namespace[name] = type(
            name,
            bases,
            # __module__ so test ids name the registering module, not this one.
            {"server": server, "__module__": namespace.get("__name__", __name__)},
        )
