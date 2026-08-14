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
   against, with an empty (or not-yet-existing) directory to write into::

       vnclog --capture ./my-bug-capture --listen 5902 -s YOURSERVER::5900

   ``vnclog`` will refuse to run if ``./my-bug-capture`` already exists and
   is non-empty -- that's deliberate, so a capture is never silently mixed
   with an older one.

3. Point your VNC client at the proxy instead of the real server --
   ``localhost::5902`` -- and reproduce the problem. This can be your usual
   GUI viewer, or a ``vncdo`` script if the bug is scriptable::

       vncdo -s localhost::5902 key enter type "hello" capture screen.png

4. Stop the proxy (Ctrl-C) once you're done. It flushes and closes the
   capture when your client disconnects, not only on a clean process exit,
   so a Ctrl-C is safe.

5. Attach the whole ``my-bug-capture`` directory to the GitHub issue (zip it
   first if your attachment tool doesn't take directories).

What's in the directory
-------------------------

::

    session.vdo   # the vncdo commands/events driven through the proxy
    s2c.bin       # raw server-to-client byte stream, in arrival order
    c2s.bin       # raw client-to-server byte stream, in arrival order
    meta.json     # server address, vncdotool version, capture timestamp,
                  # the server's protocol version string, the security
                  # types it offered, the framebuffer geometry, and what
                  # was (and was not) scrubbed

Only one session is ever recorded per ``--capture DIR``: if a second client
connects (a viewer retrying after a dropped connection, say) it is refused
outright rather than silently overwriting the capture you already have.
Start a fresh ``vnclog --capture`` into a new directory to record another
session.

``meta.json`` is plain, human-readable JSON -- open it and read it before
you attach the capture. It tells you exactly what got redacted, so you can
confirm nothing else in the two ``.bin`` files needs to be trimmed by hand
before it leaves your machine.

What is scrubbed
------------------

Two things are redacted at capture time, before any byte touches disk:

* the 16-byte VNC authentication challenge (sent by the server) and the
  16-byte response (sent by the client), each replaced with an all-zero
  marker of the same length so the surrounding byte offsets don't shift;
* any bytes matching the VNC password vncdotool itself was given (via
  ``-p``/``--password``), wherever they occur in either stream.

Both are also listed by name in ``meta.json``'s ``scrubbed`` field, so you
don't have to take it on faith -- e.g. ``["vnc-auth-challenge",
"vnc-auth-response"]``, or ``[]`` if the server used no authentication at
all.

.. warning::

   **Apple Remote Desktop / Diffie-Hellman auth (macOS Screen Sharing) is
   not scrubbed.** If ``meta.json``'s ``unscrubbed_auth`` field is set
   (e.g. ``"diffie-hellman(30)"``) instead of ``null``, the capture
   contains that key exchange -- including your username and
   DES/AES-wrapped password -- verbatim in ``s2c.bin``/``c2s.bin``. ARD's
   512-bit Diffie-Hellman is within reach of offline compute today, so
   treat such a capture as containing your credentials in a weakly
   protected form. Do **not** attach it to a public issue; email it to a
   maintainer instead, or reproduce the bug against a server that uses VNC
   password auth or no auth if that's an option for you.

What is **not** scrubbed
--------------------------

Everything else in the capture is recorded as-is. In particular:

* **screen contents** -- framebuffer updates are the whole point of the
  protocol, and they are not redacted;
* **clipboard text** -- cut/paste text sent in either direction is captured
  in the clear;
* **typed text** -- keystrokes you send through the proxy (including
  anything you type into a password field *inside* the remote session, as
  opposed to the VNC connection password itself) are recorded exactly as
  sent.

Do not reproduce a bug through the capture proxy while entering anything you
would not want to see attached to a public GitHub issue. If your reproduction
requires it, redact the relevant bytes from ``s2c.bin``/``c2s.bin`` by hand
before attaching -- the file format is deliberately simple (three flat
files plus JSON metadata) so that's a plain byte-offset edit, not a special
tool.

Replaying a capture
---------------------

Captures are discovery evidence attached to an issue, not a fixture that
lives in the repository or runs in CI -- see ``docs/testing-framework-design.md``
in the source tree for the full picture. A maintainer investigating your
issue may replay ``s2c.bin`` at a real client using an in-repo development
tool to narrow down the bug, and the end result of that investigation is a
small, deterministic unit test with the relevant bytes inlined -- not the
capture itself.
