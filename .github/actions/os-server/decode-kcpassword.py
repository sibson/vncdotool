#!/usr/bin/env python3
"""Print the auto-login password macOS keeps in /etc/kcpassword.

Enabling GUI auto-login stores the account's password obfuscated rather than
hashed, because loginwindow has to replay it: the bytes are XORed against a
fixed 11-byte key and NUL-padded to a multiple of its length. GitHub's runner
images do exactly this, with this key, in
images/macos/scripts/build/configure-autologin.sh.

Reads only, and only a root-readable file. Exits non-zero when there is
nothing usable to print, so the caller can fall back rather than interpret
rubbish as a password.
"""

import sys

KEY = bytes([125, 137, 82, 35, 210, 188, 221, 234, 163, 185, 31])
KCPASSWORD = "/etc/kcpassword"


def decode(data: bytes) -> bytes:
    plain = bytes(byte ^ KEY[i % len(KEY)] for i, byte in enumerate(data))
    # Padding is NUL bytes appended to the password, so the first one ends it.
    return plain.split(b"\x00")[0]


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else KCPASSWORD
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        print(f"cannot read the auto-login file: {exc}", file=sys.stderr)
        return 1

    try:
        secret = decode(data).decode("utf-8", "strict")
    except UnicodeDecodeError:
        # The file has been written by something whose format we don't know,
        # which has happened before: actions/runner-images#5231 shipped images
        # whose kcpassword was UTF-8 encoded rather than raw bytes.
        print("the auto-login file did not decode to text", file=sys.stderr)
        return 1

    if not secret:
        print("the auto-login file decoded to nothing", file=sys.stderr)
        return 1

    # Handing the decoded value to the caller is the entire job, and stdout is
    # the only channel a `sudo` child has back to it. It goes to a pipe, not a
    # log: the caller registers it as a mask before anything can echo it.
    sys.stdout.write(secret)  # codeql[py/clear-text-logging-sensitive-data]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
