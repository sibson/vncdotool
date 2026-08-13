#!/usr/bin/env python3
"""Wire-level replay of TightVNC-on-Windows first-update behaviour (issue #90).

A minimal RFB 3.3 server. On the client's first (non-incremental)
FramebufferUpdateRequest it answers the way the TightVNC server does in the
issue's `-v` logs: a FramebufferUpdate containing ONLY the DesktopSize
pseudo-rectangle (-223) — geometry, no pixels — followed a moment later by a
second update carrying the real RAW frame. A well-behaved mode (--pixels-first)
answers the first request with the RAW frame directly, libvncserver-style.

The frame is a recognisable test pattern (gradient + checker) so a correct
capture is unmistakable next to a black one.

Usage:  python3 fake_tightvnc.py --port 5999 [--pixels-first] [--delay 0.15]
"""
import argparse
import socket
import struct
import sys
import time

W, H = 1024, 640
NAME = b"issue-90-repro"

# bpp=32 depth=24 bigendian=0 truecolor=1 max=255,255,255 shift r=0 g=8 b=16
# == vncdotool's RGB32 / Pillow "RGBX" (client.py PF2IM), also the unit-test
# constant in tests/unit/test_client.py.
PIXEL_FORMAT = struct.pack("!BBBBHHHBBBxxx", 32, 24, 0, 1, 255, 255, 255, 0, 8, 16)


def make_frame() -> bytes:
    buf = bytearray(W * H * 4)
    for y in range(H):
        g = (255 * y) // H
        row_checker = (y // 64) % 2
        base = y * W * 4
        for x in range(W):
            r = (255 * x) // W
            b = 200 if ((x // 64) % 2) ^ row_checker else 40
            o = base + x * 4
            buf[o] = r
            buf[o + 1] = g
            buf[o + 2] = b
    return bytes(buf)


FRAME = make_frame()


def fbu_desktop_size() -> bytes:
    return struct.pack("!BxH", 0, 1) + struct.pack("!HHHHi", 0, 0, W, H, -223)


def fbu_raw_frame() -> bytes:
    return struct.pack("!BxH", 0, 1) + struct.pack("!HHHHi", 0, 0, W, H, 0) + FRAME


def recv_exact(sock: socket.socket, n: int) -> bytes:
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("client closed")
        data += chunk
    return data


def serve_client(sock: socket.socket, mode: str, delay: float) -> None:
    def log(m: str) -> None:
        print(f"[server] {m}", flush=True)
    sock.sendall(b"RFB 003.003\n")
    log(f"client version: {recv_exact(sock, 12)!r}")
    sock.sendall(struct.pack("!I", 1))  # RFB 3.3: server dictates auth = None
    log(f"ClientInit shared={recv_exact(sock, 1)!r}")
    sock.sendall(
        struct.pack("!HH", W, H) + PIXEL_FORMAT + struct.pack("!I", len(NAME)) + NAME
    )
    log(f"ServerInit sent ({W}x{H}, RGBX)")

    first_request = True
    while True:
        mtype = recv_exact(sock, 1)[0]
        if mtype == 0:  # SetPixelFormat
            recv_exact(sock, 19)
            log("client: SetPixelFormat (ignored; client accepted native format)")
        elif mtype == 2:  # SetEncodings
            (count,) = struct.unpack("!xH", recv_exact(sock, 3))
            encs = struct.unpack(f"!{count}i", recv_exact(sock, 4 * count))
            log(f"client: SetEncodings {encs}")
        elif mtype == 3:  # FramebufferUpdateRequest
            inc, x, y, w, h = struct.unpack("!BHHHH", recv_exact(sock, 9))
            log(f"client: FramebufferUpdateRequest incremental={inc} {x},{y} {w}x{h}")
            if first_request and mode == "tightvnc":
                first_request = False
                sock.sendall(fbu_desktop_size())
                log("sent: FramebufferUpdate [1 rect: DesktopSize -223, NO pixels]")
                time.sleep(delay)
                try:
                    sock.sendall(fbu_raw_frame())
                    log(f"sent: FramebufferUpdate [1 rect: RAW {W}x{H} pixel data]")
                except OSError:
                    log("could not send pixel data: CLIENT ALREADY DISCONNECTED")
                    return
            else:
                first_request = False
                sock.sendall(fbu_raw_frame())
                log(f"sent: FramebufferUpdate [1 rect: RAW {W}x{H} pixel data]")
        elif mtype == 4:  # KeyEvent
            recv_exact(sock, 7)
        elif mtype == 5:  # PointerEvent
            recv_exact(sock, 9)
        elif mtype == 6:  # ClientCutText
            (ln,) = struct.unpack("!3xI", recv_exact(sock, 7))
            recv_exact(sock, ln)
        else:
            log(f"unexpected client message type {mtype}")
            return


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=5999)
    p.add_argument("--pixels-first", action="store_true",
                   help="well-behaved mode: answer the first update request with pixel data")
    p.add_argument("--delay", type=float, default=0.15,
                   help="tightvnc mode: seconds between DesktopSize update and pixel update")
    p.add_argument("--once", action="store_true", help="serve one connection and exit")
    args = p.parse_args()
    mode = "pixels-first" if args.pixels_first else "tightvnc"

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", args.port))
    srv.listen(1)
    print(f"[server] mode={mode} listening on 127.0.0.1:{args.port}", flush=True)
    while True:
        sock, addr = srv.accept()
        print(f"[server] connection from {addr}", flush=True)
        try:
            serve_client(sock, mode, args.delay)
        except ConnectionError as e:
            print(f"[server] {e}", flush=True)
        finally:
            sock.close()
        if args.once:
            return 0


if __name__ == "__main__":
    sys.exit(main())
