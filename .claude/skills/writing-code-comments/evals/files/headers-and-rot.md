# Task

Audit the comments below. Classify EACH block: **delete**, **rewrite**, or
**keep**. Where you say rewrite, write the replacement out in full. One line of
reasoning per block, then a count by verdict.

## Repo conventions (from CLAUDE.md)

Comment what is surprising and particular to this code. Rationale for
non-obvious choices goes in the commit body, not the code.

## Context

The functional test module was renamed in this branch: `test_os_servers.py` no
longer exists, and its scenarios now live in `test_server_compat_native.py` and
`test_server_compat_docker.py`. Nothing else in the repo still refers to the
old name.

The GitHub Actions workflow is `.github/workflows/ci.yml`. The `paths-ignore`
key described in Block 2 is fifty lines further down the same file, under the
`on:` block.

## Block 1 --- scripts/enable-screen-sharing.sh

```bash
#!/bin/sh
# Turn this macOS machine into a live Screen Sharing server for
# tests/functional/test_os_servers.py. See that file for the scenarios it
# runs.
```

## Block 2 --- .github/workflows/ci.yml, at the very top of the file

```yaml
name: VNCDotool CI

# paths-ignore skips the run only when every changed file matches, so a commit
# that touches docs/ and vncdotool/ still runs the full suite.

on:
  push:
```

## Block 3 --- tests/functional/utils.py

```python
# This module holds the helpers shared by the functional tests: server
# fixtures, the console-script paths, and the image comparison. It reads
# VNCDOTOOL_TEST_SERVERS and VNCDOTOOL_TEST_TIMEOUT from the environment.

import os
```

## Block 4 --- vncdotool/client.py

```python
    def captureScreen(self, filename):
        # Called from vncdo's `capture` command and from api.connect()'s
        # captureScreen wrapper.
        return self._capture(filename)
```

## Block 5 --- tests/servers/docker-compose.yml

```yaml
services:
  # x11vnc is the only server in the fleet that reports a depth of 24 while
  # announcing a 32-bit pixel format, which is what the rgbx8888 golden was
  # captured against.
  x11vnc:
    image: vncdotool/x11vnc:latest
```
