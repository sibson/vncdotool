# Raw QEMU/KVM on Linux

A VNC server for vncdotool to test against on a Linux machine (a GitHub
`ubuntu-latest` runner in CI), started raw on the machine rather than in a
container. `setup.sh` installs QEMU and starts it;
`tests/functional/test_server_compat_native.py` then runs the same connect/type/capture
round trip used for the Docker servers, and `collect-diagnostics.sh` gathers
the evidence when something goes wrong.

```sh
bash tests/servers/qemu-kvm/setup.sh
uv run python -m unittest discover -v -s tests/functional -t . -p 'test_server_compat_native.py'
```

This leaves an unauthenticated VNC server listening on loopback, so only run
it on a throwaway machine.

Why this server is raw rather than a container, when Tier 1 already has a
`qemu` compose service: `specs/server-compatibility-plan.md`, Tier 2.

## What the setup has to get right

* **There is no guest, and that is deliberate.** With no `-drive` and no
  `-kernel`, the machine stops at the firmware's "no bootable device"
  screen. That is still a real framebuffer served by QEMU's own RFB code,
  and it costs no guest image to download and no boot to wait for.

* **`-vnc :0` listens on every interface.** QEMU's VNC server has no
  authentication unless it is started with `password=on` *and* a password is
  then set over the monitor, so the listen address is the only thing
  standing between an open runner port and the internet. `setup.sh` binds
  `127.0.0.1:0`.

* **`/dev/kvm` is root-only until you open it.** Hosted runners ship it as
  `root:kvm` mode 0660 with the runner user outside that group. `setup.sh`
  installs the same udev rule the Android emulator actions use, and fails
  rather than falling back to emulation — a silent fall back to TCG would
  report a passing "KVM" job that never touched KVM.

* **Accelerator is a variable, not a constant.** `VNCDOTOOL_QEMU_ACCEL=tcg`
  runs this same script on a developer machine with no `/dev/kvm` (macOS, or
  a VM without nested virtualisation). What that proves is script mechanics
  and the RFB round trip, not the accelerated path CI exercises.

* **Registration is opt-in, not automatic.** `utils.py` registers
  `QEMU_KVM` only when `VNCDOTOOL_OS_SERVER_LINUX=1` is set, because other
  CI jobs share the Linux runners and never run this script. `setup.sh`
  sets it through `$GITHUB_ENV` in CI; locally it can only tell you to
  export it yourself, since a script cannot set a variable in the shell
  that called it.

## Readiness

An open RFB port is closer to readiness here than on the other two Tier 2
servers: QEMU binds its VNC socket as part of starting up, and the firmware
has drawn its screen within a second or so. CI still runs the shared gate
(`tests/functional/wait_for_servers.py os`) so a slow start shows up as a
wait rather than as a timeout inside a test.

## What it proves, and what it doesn't

QEMU's RFB implementation is its own, not LibVNCServer's or TigerVNC's, so
this covers a distinct server: its version string, its security-type
negotiation, the encodings and pixel formats it offers, and its
QEMU-specific pseudo-encodings.

Captures come back with real content rather than the flat black a hosted
macOS runner gives: the firmware's text screen is 720x400 in the default VGA
text mode, drawn in a handful of colours.

It does not cover a guest. Key and pointer events are accepted by the server
and delivered to a machine with nothing running on it, so nothing types
back and no event sink can confirm them — the input scenarios assert the
protocol round trip only. The screen size is whatever VGA mode the firmware
left behind rather than a geometry we asked for, so it isn't asserted
either.
