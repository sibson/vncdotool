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

Replaying a capture (maintainers)
-----------------------------------

``tests/tools/replay_capture.py`` serves a capture back at a real VNC client,
so a bug against a server nobody here can run becomes reproducible on a
laptop. It is a maintainer's tool: never shipped, never a CI fixture. The
end product of a replay session is a unit test with the relevant bytes
inlined, not the capture itself.

::

    python tests/tools/replay_capture.py ./my-bug-capture.zip --verbose

That serves the archive *and* drives it: the tool forks ``vncdo`` on the
archive's own ``session.vdo``, so the client sends the events the original
one sent, in the order it sent them. Anything else is a different session,
and a replay of a different session is not evidence. The replay ends on a
screenshot -- ``replay.png`` in a fresh temporary directory, both settable
with ``--screenshot`` and ``--workdir`` -- and the tool exits with
``vncdo``'s own status.

``--no-client`` listens and stops there, for driving the replay from a GUI
viewer or a hand-written ``vncdo`` line instead::

    python tests/tools/replay_capture.py ./my-bug-capture.zip --no-client
    vncdo -s 127.0.0.1::5999 key enter type "hello" capture screen.png

Passing a file that is not a zip archive runs it as a hand-written scenario
instead of a recording: a Python file defining a ``MESSAGES`` list of
``bytes`` to send, ``("wait", nbytes)`` to block until the client has sent
that much, or ``("pause", seconds)``. It is ``exec()``'d -- **scripts are
trusted developer code**, like a local config file. Use it to force a case
no capture reproduces; there is no recorded session to drive, so it implies
``--no-client``.

Auth is replaced, not replayed
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The recorded handshake is not what the bug is usually in, and replaying it
means reproducing the original client's auth setup exactly -- the same
password, the same security type -- before you can even reach the session.
So the replay keeps the recorded greeting, offers ``none`` and nothing else,
skips the recorded auth exchange, and picks the recording back up at
ServerInit. Any client connects, no password needed, whatever the capture
negotiated.

``--replay-auth`` serves the recorded handshake verbatim, for a bug that
lives in the negotiation itself. It is also the automatic fallback when the
archive has no usable ``c2s.bin``, since where the handshake ends is read
off the client's side of the recording. Two things then apply again:

* A VNC-authenticated capture has its challenge and response zeroed, so a
  real client's response to the replayed all-zero challenge can never match
  what the original server expected. ARD captures are the opposite case:
  the key exchange is in the clear and replays exactly.
* Recorded bytes past the security-type choice only fit the auth path the
  original client took. Sending them to a client that chose differently
  desyncs it silently -- challenge bytes get read as something else
  entirely -- so the replay reads ``c2s.bin`` to learn what the original
  session negotiated, and closes the connection with an error rather than
  mislead you.

Waiting for the client
~~~~~~~~~~~~~~~~~~~~~~~~

The handshake is a conversation: the client replies partway through, and
what it says next depends on what it was sent. So the handshake goes out a
step at a time, against the client's real replies. Under ``--replay-auth``
those steps come from the same grammar the capture scrubber uses, which is
what keeps the two from drifting apart.

Past ServerInit the recorded framebuffer waits for the client's first
FramebufferUpdateRequest. A capture holds one finite recording of the
screen, so those bytes get exactly one chance to be useful: sent before the
client asked, they go past a client that asks a moment later, which then
waits forever for an update that has already been and gone.

Once the recording runs out the connection is left open. The original
server hung up because its client did, and hanging up here instead would
cut short whatever the live client is still doing with the bytes it has.

Because an unscrubbed capture can replay credentials verbatim, the tool
binds to ``127.0.0.1``. Pass ``--bind`` only for a capture you know carries
nothing sensitive.
