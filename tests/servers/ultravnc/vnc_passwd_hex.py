#!/usr/bin/env python3
"""Compute the ``passwd=`` value ultravnc.ini needs for a given password.

Run as a script it writes that hex to the file named as its second
argument, for setup.ps1 to read back into the ini.

UltraVNC refuses every incoming connection until a password is set, and it
stores that password in ultravnc.ini using the classic VNC password-*file*
obfuscation -- the one behind ~/.vnc/passwd across the whole VNC family,
originally AT&T's vncauth.c: the password, null padded to 8 bytes, DES
encrypted under a fixed well-known key.

Note this is the opposite pairing to the RFB authentication challenge
response in vncdotool.rfb, where the *password* derives the key and the
server's challenge is the plaintext. Both apply the same per-byte bit
reversal to the key, which is why reverse_bits() is shared between them.

The obfuscation is not encryption: anyone who can read the ini can recover
the password. That is inherent to how UltraVNC stores it, and is why this
is only ever used with throwaway credentials on a throwaway machine.
"""

import sys
from pathlib import Path

# Allow running straight from a checkout, without vncdotool installed.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from vncdotool.rfb import des_encrypt, reverse_bits  # noqa: E402

# The fixed key from vncauth.c, shared by every VNC password file.
VNCAUTH_KEY = bytes([23, 82, 107, 6, 35, 78, 88, 7])


def vnc_passwd_hex(password: str) -> str:
    """Obfuscated hex for ``password``, as ultravnc.ini stores it."""
    plaintext = f"{password:\0<8.8}".encode("ascii")
    obfuscated = des_encrypt(reverse_bits(VNCAUTH_KEY), plaintext)
    # UltraVNC writes a trailing null byte after the 8 encrypted ones.
    return (obfuscated + b"\x00").hex()


def main(argv: list) -> int:
    if len(argv) != 3:
        print(f"usage: {Path(argv[0]).name} PASSWORD OUTPUT_FILE", file=sys.stderr)
        return 2

    # Written to a file rather than printed: the hex is as good as the
    # password to anyone who has it, and stdout of a CI step is the last
    # place a credential should end up.
    password, output = argv[1], Path(argv[2])
    output.write_text(vnc_passwd_hex(password), encoding="ascii")
    print(f"wrote the ultravnc.ini password hex to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
