Capturing a session for a bug report
=====================================

vncdotool is tested against the servers we can run ourselves (see
``tests/servers/``). If you hit a bug against a server we can't host --
RealVNC, Proxmox, a vendor's embedded VNC implementation, whatever -- the
most useful thing you can attach to the issue is a *capture*: a recording of
the raw bytes vncdotool exchanged with that server while reproducing the
problem.

You do not need a checkout of this repository to make one. A released,
``pip``-installed vncdotool is enough.

Making a capture
------------------

1. Install vncdotool::

       pip install vncdotool

2. Start the recording proxy, pointed at the server you're seeing the bug
   against, naming the ``.zip`` to write::

       vnclog --capture-raw ./my-bug-capture.zip --listen 5902 -s YOURSERVER::5900

   ``vnclog`` will refuse to run if ``./my-bug-capture.zip`` already exists
   -- that's deliberate, so a capture is never silently overwritten.

3. Point your VNC client at the proxy instead of the real server --
   ``localhost::5902`` -- and reproduce the problem. This can be your usual
   GUI viewer, or a ``vncdo`` script if the bug is scriptable::

       vncdo -s localhost::5902 key enter type "hello" capture screen.png

4. Stop the proxy (Ctrl-C) once you're done. It writes the archive when your
   client disconnects, not only on a clean process exit, so a Ctrl-C is
   safe.

5. Attach ``my-bug-capture.zip`` to the GitHub issue.

What's in the archive
-----------------------

::

    session.vdo   # the vncdo commands/events driven through the proxy
    s2c.bin       # raw server-to-client byte stream, in arrival order
    c2s.bin       # raw client-to-server byte stream, in arrival order
    meta.json     # server address, vncdotool version, capture timestamp,
                  # the server's protocol version string, the security
                  # types it offered, which encodings it actually sent,
                  # and the framebuffer geometry

The archive is written whole, under a temporary name and renamed into place,
so a half-written capture never looks like a complete one.

Only one session is ever recorded per ``--capture-raw``: if a second client
connects (a viewer retrying after a dropped connection, say) it is refused
outright rather than silently overwriting the capture you already have.
Start a fresh ``vnclog --capture-raw`` with a new filename to record another
session.

``meta.json`` is plain, human-readable JSON -- open it and read it before
you attach the capture, so you know what is about to leave your machine.

``encodings_seen`` is counted from the rectangles the server actually sent,
not from what the client asked for -- a server is free to ignore the
client's ``SetEncodings`` -- so it answers "which encodings does this server
really use?" directly::

    "encodings_seen": [
      {"encoding": 0,  "name": "raw",  "rectangles": 3},
      {"encoding": 16, "name": "zrle", "rectangles": 118}
    ]

An encoding vncdotool has no name for shows as ``"name": null`` with its
number intact, which is itself a useful bug report.

What is scrubbed
------------------

Credentials are redacted at capture time, before any byte touches disk.
Redactions are always replaced by the same number of zero bytes, so the
surrounding byte offsets don't shift and the capture still replays:

* **VNC authentication** -- the 16-byte challenge (from the server) and the
  16-byte response (from the client);
* **ARD / Apple Screen Sharing** (``diffie-hellman``, macOS) -- the 128-byte
  AES block carrying your username and password. The Diffie-Hellman values
  around it (generator, modulus, both public keys) are public by
  construction and are kept deliberately: ARD compatibility bugs live in
  those values.

vncdotool can only redact an exchange it can parse. If the session
negotiates an auth type it cannot -- ``tight``, ``vencrypt``, ``rsa-aes``,
UltraVNC's MS-Logon -- the capture is aborted and the error tells you how to
proceed anyway.

.. warning::

   ``--capture-raw-unsafe-auth`` writes the credential exchange to the
   archive verbatim, and ``meta.json``'s ``unscrubbed_auth`` records which
   type it was. Some of these exchanges are attackable offline -- ARD's
   512-bit Diffie-Hellman is within reach of ordinary compute today. Use a
   **disposable password, and rotate it afterwards**, and prefer emailing
   such a capture to a maintainer over attaching it to a public issue.

What is **not** scrubbed
--------------------------

Scrubbing stops at the end of the handshake. Everything the session itself
carries is recorded as-is -- deliberately: a capture with its input stream
rewritten is no longer evidence of what the server did. In particular:

* **screen contents** -- framebuffer updates are the whole point of the
  protocol, and they are not redacted;
* **clipboard text** -- cut/paste text sent in either direction is captured
  in the clear;
* **typed text** -- keystrokes you send through the proxy (including
  anything you type into a password field *inside* the remote session, as
  opposed to the VNC connection password itself) are recorded exactly as
  sent.

Do not reproduce a bug through the capture proxy while entering anything you
would not want to see attached to a public GitHub issue -- in particular, do
not type a password into the remote desktop during a capture. If your
reproduction requires it, unzip the archive, redact the relevant bytes from
``s2c.bin``/``c2s.bin`` by hand, and rezip -- the format is deliberately
simple (three flat files plus JSON metadata) so that's a plain byte-offset
edit, not a special tool.

Replaying a capture
---------------------

Captures are discovery evidence attached to an issue, not a fixture that
lives in the repository or runs in CI -- see ``docs/testing-framework-design.md``
in the source tree for the full picture. A maintainer investigating your
issue may replay ``s2c.bin`` at a real client using an in-repo development
tool to narrow down the bug, and the end result of that investigation is a
small, deterministic unit test with the relevant bytes inlined -- not the
capture itself.
