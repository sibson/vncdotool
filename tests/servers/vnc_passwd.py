#!/usr/bin/env python3
"""Compute the obfuscated password blob a Windows VNC server stores.

UltraVNC, TightVNC and TigerVNC all store the password the same way: the
classic VNC password-*file* obfuscation behind ~/.vnc/passwd across the whole
VNC family, originally AT&T's vncauth.c -- the password, null padded to 8
bytes, DES encrypted under a fixed well-known key. Only where they put it
differs: ultravnc.ini takes hex text, the other two take REG_BINARY.

Note this is the opposite pairing to the RFB authentication challenge
response in vncdotool.rfb, where the *password* derives the key and the
server's challenge is the plaintext. Both apply the same per-byte bit
reversal to the key, which is why reverse_bits() is shared between them.

The obfuscation is not encryption: anyone who can read the ini or the
registry can recover the password. That is inherent to how these servers
store it, and is why this is only ever used with throwaway credentials on a
throwaway machine.
"""

import argparse
import sys
from pathlib import Path

# Allow running straight from a checkout, without vncdotool installed.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from vncdotool.rfb import des_encrypt, reverse_bits  # noqa: E402

VNCAUTH_KEY = bytes([23, 82, 107, 6, 35, 78, 88, 7])


def vnc_passwd(password: str) -> bytes:
    """The eight obfuscated bytes every one of these servers stores."""
    plaintext = f"{password:\0<8.8}".encode("ascii")
    return des_encrypt(reverse_bits(VNCAUTH_KEY), plaintext)


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("password")
    # Written to a file rather than printed: the hex is as good as the
    # password to anyone who has it, and stdout of a CI step is the last
    # place a credential should end up.
    parser.add_argument("output", type=Path, help="file to write the hex to")
    parser.add_argument(
        "--trailing-null",
        action="store_true",
        help="append the ninth byte ultravnc.ini writes after the eight",
    )
    options = parser.parse_args(argv[1:])

    blob = vnc_passwd(options.password)
    if options.trailing_null:
        blob += b"\x00"
    options.output.write_text(blob.hex(), encoding="ascii")
    print(f"wrote the obfuscated password hex to {options.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
