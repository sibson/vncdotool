# Task

You are auditing the comments in a pull request you yourself just wrote.
Classify EACH comment block below: **delete**, **rewrite**, or **keep**.

Give your verdict per block, one line of reasoning each. Then a count by verdict.

## Repo conventions (from CLAUDE.md)

A comment carries what the reader cannot get anywhere else: something
surprising, particular to this code, and absent from the language, the
library's documentation, the RFB specs and the code itself.

The reader knows the tools and can read the code, and an AI reader has every
public document already. Anything they could look up, infer from a name, or
learn by running it is not worth writing, and neither is anything about the
change rather than the code -- the alternative you rejected, what used to be
here, who calls it, the issue or PR it came from. That is commit-message and
`docs/` material. Point elsewhere only when there is something surprising
there too long to state here.

Test by deleting it: keep it only if an intelligent reader would still be
surprised later. Shortening an unnecessary comment leaves an unnecessary
comment. One or two lines is the norm.

## Context

The PR does two things: it publishes five Docker test-server images to a
registry (GHCR) so CI pulls them instead of rebuilding, and it shortens the
container teardown timeout.

The commit that introduced the registry work has this in its message body:

> The tag is that directory's git tree hash, so it changes exactly when the
> fleet does. It covers more than the build inputs -- editing an UltraVNC
> script rebuilds images it cannot affect -- which is the safe direction: a
> hash over hand-listed inputs goes stale silently the first time someone
> adds a COPY without updating the list.
>
> Pull failure falls back to building, so a PR that edits tests/servers (its
> images do not exist until it lands) and a fork PR (no registry access)
> behave as they did before.

The commit that introduced the teardown change has this in its message body:

> vncev and libvncserver-example run their upstream binary as PID 1 with no
> SIGTERM handling, so they eat the full default 10s stop grace period before
> Docker SIGKILLs them -- the other three services already exit in under a
> second via their entrypoint traps. Saves ~8s off the servers job.

A design document in the repo, `specs/server-compatibility-plan.md`, already
carries an entry recording that `type=gha` layer caching was measured and came
out slower than plain building, and that GHCR is the chosen route instead.

## Block 1 --- .github/workflows/fleet-images.yml, at the top of the file

```yaml
name: Fleet images

# The tag is deliberately coarser than the build inputs: anything under
# tests/servers rebuilds, including scripts that reach no image. Narrowing
# it to a hand-listed set goes stale silently the first time someone adds a
# COPY and forgets the list.
#
# A tag maps to one set of apt packages forever, so Debian security updates
# never arrive on their own -- dispatch this by hand to rebuild the current
# tree against today's packages.
#
# specs/server-compatibility-plan.md records why this rather than `type=gha`
# layer caching, which measured slower than building.

on:
  push:
    branches: [main]
    paths: ['tests/servers/**']
  workflow_dispatch:
```

## Block 2 --- .github/workflows/ci.yml

```yaml
      # Images come from .github/workflows/fleet-images.yml. A pull miss is
      # expected rather than a failure: a PR that edits tests/servers has no
      # published images until it lands, and fork PRs cannot reach the
      # registry.
      - name: Resolve the fleet image tag
        run: echo "FLEET_TAG=$(git rev-parse HEAD:tests/servers)" >> "$GITHUB_ENV"

      - name: Fetch or build the VNC test servers
        run: |
          docker compose -f tests/servers/docker-compose.yml pull --quiet \
            || docker compose -f tests/servers/docker-compose.yml build
          docker compose -f tests/servers/docker-compose.yml up -d --wait
```

## Block 3 --- .github/workflows/ci.yml, further down

```yaml
      # vncev and libvncserver-example run their upstream binary as PID 1
      # with no SIGTERM handling, so they sit out the whole grace period;
      # the other three trap and exit in under a second. Nothing here needs
      # a clean shutdown.
      - name: Stop the VNC test servers
        if: always()
        run: docker compose -f tests/servers/docker-compose.yml down --timeout 2
```

## Block 4 --- tests/servers/docker-compose.yml, appended to an existing header comment

```yaml
# Readiness is the HEALTHCHECK baked into the image, which makes
# `up --wait` a reliable barrier. Every service publishes its RFB port to
# localhost only.
#
# CI sets FLEET_IMAGE_PREFIX and FLEET_TAG to pull these prebuilt rather
# than build them; see .github/workflows/fleet-images.yml.

name: vncdo-test-servers

services:
  tigervnc:
    build:
      context: .
      target: tigervnc
    image: ${FLEET_IMAGE_PREFIX:-vncdotool-test}-tigervnc:${FLEET_TAG:-dev}
```
