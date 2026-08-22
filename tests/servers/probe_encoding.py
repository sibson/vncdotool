"""Offer one encoding, then request several regions, reporting each rectangle.

    python tests/servers/probe_encoding.py <port> <encoding-number> [...]

Speaks RFB 3.8 down a socket rather than going through vncdotool, so what it
reports is the server's choice and not this client's idea of it. Handles None
auth and the Raw, RRE and CoRRE rectangle bodies -- enough to walk an update
made of the encoding under test, and no further.
"""
import socket
import struct
import sys

NAMES = {0: "Raw", 1: "CopyRect", 2: "RRE", 4: "CoRRE", 5: "Hextile", 16: "ZRLE", 7: "Tight", 15: "TRLE"}


def recvall(s, n):
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise EOFError(f"wanted {n}, got {len(buf)}")
        buf += chunk
    return buf


def main():
    port = int(sys.argv[1])
    encodings = [int(a) for a in sys.argv[2:]]
    s = socket.create_connection(("127.0.0.1", port), timeout=10)
    print("server version:", recvall(s, 12).decode().strip())
    s.sendall(b"RFB 003.008\n")
    ntypes = recvall(s, 1)[0]
    types = list(recvall(s, ntypes))
    assert 1 in types, f"probe only handles None auth, got {types}"
    s.sendall(bytes([1]))
    (result,) = struct.unpack("!I", recvall(s, 4))
    assert result == 0, f"security result {result}"
    s.sendall(bytes([1]))
    width, height = struct.unpack("!HH", recvall(s, 4))
    pf = recvall(s, 16)
    bpp = pf[0]
    bypp = bpp // 8
    (namelen,) = struct.unpack("!I", recvall(s, 4))
    print(f"desktop: {recvall(s, namelen).decode()} {width}x{height} bpp={bpp}")

    s.sendall(struct.pack("!BBH", 2, 0, len(encodings)) + b"".join(struct.pack("!i", e) for e in encodings))
    print("offered:", [NAMES.get(e, e) for e in encodings])

    regions = [(0, 0, width, height), (0, 0, 16, 16), (32, 32, 64, 48), (width - 8, height - 8, 8, 8)]
    for (rx, ry, rw, rh) in regions:
        print(f"request {rw}x{rh}+{rx}+{ry}")
        s.sendall(struct.pack("!BBHHHH", 3, 0, rx, ry, rw, rh))
        msg = recvall(s, 1)[0]
        assert msg == 0, f"unexpected message type {msg}"
        recvall(s, 1)
        (nrects,) = struct.unpack("!H", recvall(s, 2))
        for i in range(nrects):
            x, y, w, h, enc = struct.unpack("!HHHHi", recvall(s, 12))
            print(f"    rect {i}: {w}x{h}+{x}+{y} encoding={enc} ({NAMES.get(enc, '?')})")
            if enc == 0:
                recvall(s, w * h * bypp)
            elif enc == 2:
                (n,) = struct.unpack("!I", recvall(s, 4))
                recvall(s, bypp + n * (bypp + 8))
            elif enc == 4:
                (n,) = struct.unpack("!I", recvall(s, 4))
                recvall(s, bypp + n * (bypp + 4))
            else:
                print("    (cannot parse further; stopping)")
                return


main()
