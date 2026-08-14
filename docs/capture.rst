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

3. Point your VNC client at the proxy instead of the real server --
   ``localhost::5902`` -- and reproduce the problem. This can be your usual
   GUI viewer, or a ``vncdo`` script if the bug is scriptable::

       vncdo -s localhost::5902 key enter type "hello" capture screen.png

4. Disconnect. ``vnclog`` writes the archive and exits.

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

What is scrubbed
------------------

Credentials are redacted at capture time, before any byte touches disk:

* **VNC authentication** -- the 16-byte challenge and the 16-byte response;
* **ARD / Apple Screen Sharing** -- the AES block carrying your username and
  password. The Diffie-Hellman values around it are public by construction
  and are kept: ARD compatibility bugs live in them.

vncdotool implements those two auth types and no others, so it cannot locate
the secret inside ``tight``, ``vencrypt``, ``rsa-aes`` or UltraVNC's
MS-Logon. A session negotiating one of those aborts the capture rather than
write the credential exchange out whole; the error says how to override it.

.. warning::

   Overriding writes your credential exchange into the archive verbatim.
   Some of these are attackable offline -- ARD's 512-bit Diffie-Hellman is
   within reach of ordinary compute today. Use a **disposable password and
   rotate it afterwards.**

What is **not** scrubbed
--------------------------

Scrubbing stops at the end of the handshake. Everything the session carries
is recorded as sent: screen contents, clipboard text, and every keystroke --
including anything typed into a password field *inside* the remote desktop.

So reproduce the bug and nothing else. Do not type a password into the
remote desktop while capturing.
