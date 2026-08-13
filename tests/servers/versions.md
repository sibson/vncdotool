# Version pins: source of truth

Every pinned version, base image digest, and package used to build or run
a test VNC server is listed here, per
`docs/server-compatibility-plan.md` ("One source of version truth"). CI,
the `make` targets under `tests/servers/servers.mk`, and any fixture
`manifest.yaml` that names a server version should point back to this
table rather than re-stating the pin -- when a pin moves, this file and
the one place it lives (below) are the only two things that need to
change together.

| What | Pin | Where it lives | How to bump |
|---|---|---|---|
| Base image for all Tier 1 containers | `debian:bookworm-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241` | `tests/servers/Dockerfile`, `FROM` line of the `base` stage | Resolve a fresh digest with `docker manifest inspect debian:bookworm-slim` (or `crane digest debian:bookworm-slim`, or the registry HTTP API -- see below), update the `FROM` line and this row together, then `make servers-up` and re-run `make test-servers` to confirm the fleet still builds and passes. |
| `tigervnc-standalone-server`, `tigervnc-common`, `tigervnc-tools` | whatever `apt-get install` resolves in `bookworm` at build time (unpinned patch version -- Debian stable's own security-update policy is trusted here rather than a second, harder-to-audit pin) | `tests/servers/Dockerfile`, `tigervnc` stage `RUN apt-get install` | Bump by moving the base image pin (Debian release/point-release); to pin an exact package version instead, add `=<version>` to each package name and hold it with `apt-mark hold` in the same `RUN`. |
| `x11vnc`, `xvfb` | same as above: whatever `bookworm` has | `tests/servers/Dockerfile`, `x11vnc` stage `RUN apt-get install` | Same as the TigerVNC row. |
| `x11-apps`, `xauth`, `procps` (shared `base` stage tooling) | same as above | `tests/servers/Dockerfile`, `base` stage `RUN apt-get install` | Same as the TigerVNC row. |
| `LIBVNCSERVER_VERSION` (native source build, the no-Docker fallback and the "current git LibVNCServer" case the containers pin away from) | `0.9.14` | `libvncserver.mk`, top of file (`LIBVNCSERVER_VERSION?=0.9.14`) | Edit the variable to a new tag from https://github.com/LibVNC/libvncserver/tags, then `make libvnc-examples` (or `make test-libvnc`) to confirm it still builds; the CI cache key in `.github/workflows/ci.yml` (`functional` job, "Cache LibVNCServer build" step) is keyed on `hashFiles('libvncserver.mk')`, so bumping this line alone invalidates the cache correctly. |
| UltraVNC (Tier 2, Windows) | latest available on the Chocolatey community feed at run time (no version pin -- the feed's own versioning and the "report drift, don't block" trade-off documented in `docs/server-compatibility-plan.md`, Tier 2, cover this) | `tests/servers/ultravnc/setup.ps1`, `Install-UltraVNC`'s `choco install ultravnc -y --no-progress` | To pin, change to `choco install ultravnc --version <x.y.z.z> -y --no-progress` and record the chosen version in this row; until then, drift surfaces via the change-triggered `os-servers.yml` job rather than silently. |
| `windows-latest` runner image | GitHub-managed rolling tag, not a digest (hosted runners don't expose one to pin against) | `.github/workflows/os-servers.yml`, matrix entry `runner: windows-latest` | Switch to a dated image alias (e.g. `windows-2025`) if GitHub Actions' runner-image catalog offers one and reproducibility matters more than always testing the newest image; note the trade-off (older image, later CVE/feature drift) in this row if you do. |
| `macos-latest` runner image | GitHub-managed rolling tag, not a digest | `.github/workflows/os-servers.yml`, matrix entry `runner: macos-latest` | Same as the `windows-latest` row (e.g. `macos-15`). |

## Resolving a fresh Docker digest without a local daemon

`docker manifest inspect <image>:<tag>` needs a running daemon. Without
one (e.g. this repo's sandboxed dev environments), the registry's HTTP
API v2 gives the same answer directly:

```sh
IMAGE=library/debian TAG=bookworm-slim
TOKEN=$(curl -sS "https://auth.docker.io/token?service=registry.docker.io&scope=repository:${IMAGE}:pull" \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['token'])")
curl -sS -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.docker.distribution.manifest.list.v2+json,application/vnd.oci.image.index.v1+json" \
  "https://registry-1.docker.io/v2/${IMAGE}/manifests/${TAG}" -D - -o /dev/null \
  | grep -i docker-content-digest
```

The digest returned is the manifest *list* (multi-arch index) digest --
the same value `docker pull debian:bookworm-slim` resolves to and the
right one to pin in a `FROM` line, since Docker picks the matching
per-platform manifest from it automatically.
