# Test server port allocations

Every fleet service publishes on `127.0.0.1` only, and each one needs a host
port nothing else in the fleet claims.

**Adding a service:** take the next free port from the range its shape
belongs to, add the row here in the same commit as the compose service, and
say which pull request claims it. A port is claimed once it appears in this
file, not once it merges -- an unmerged branch still owns its number.

Container ports stay at `5900` wherever the server allows it, so the base
image's healthcheck and the compose mapping keep one shape. Where a server
insists on its own port (Selenoid listens on 4444 and bridges to a VNC
server on 5900 inside the same container) the mapping says so.

## 593x -- plain RFB over TCP

| Host | Service | Notes |
|------|---------|-------|
| 5931 | `tigervnc` | TigerVNC, no authentication |
| 5932 | `tigervnc-auth` | TigerVNC, classic VNC password |
| 5933 | `x11vnc` | x11vnc over Xvfb |
| 5934 | `vncev` | LibVNCServer event sink, renders nothing |
| 5935 | `libvncserver-example` | LibVNCServer example server |

## 594x -- transports and capabilities

| Host | Container | Service | Claimed by |
|------|-----------|---------|------------|
| 5940 | 5900 | `tigervnc-resize` | #497 |
| 5941 | 5900 | `tigervnc-vencrypt` | #498 |
| 5944 | 5900 | `qemu` | #499 |
| 5945 | 5900 | `qemu-tls` | #499 |
| 5946 | 4444 | `selenoid` | #499 |
| 5947 | 5900 | `kasmvnc` | #499 |

## 595x -- reachable over TLS and nothing else

| Host | Container | Service | Claimed by | Subtype |
|------|-----------|---------|------------|---------|
| 5951 | 5900 | `tigervnc-vencrypt-anon` | #498 | anonymous TLS |
| 5952 | 5900 | `wayvnc` | #498 | X509, with a username |

## 599x -- vnclog proxies the harness starts

Not fleet services: a test that records a session starts its own `vnclog` on
one of these and stops it again within the test, so two modules may share a
number but two live proxies may not.

| Host | Started by |
|------|------------|
| 5993, 5994, 5995 | `test_proxy.py` |
| 5996, 5997 | `test_roundtrip.py` |
| 5998 | `test_proxy.py` and `test_bandwidth.py`, never at once |
| 5999 | `tests/goldens/capture.py` |

## Not in the fleet

`5900` is the standard VNC port and belongs to whatever the developer is
running locally, so no service publishes on it. The OS-hosted servers of
`test_server_compat_native.py` are started by CI rather than by compose and
pick their own ports.
