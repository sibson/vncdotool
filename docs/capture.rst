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
                  # types it offered and the one negotiated, whether the
                  # handshake was stripped, which encodings the server
                  # actually sent, and the framebuffer geometry

The two ``.bin`` streams are what was on the wire, from the end of the
handshake on. The handshake itself is rewritten -- see below.

What is stripped
------------------

Credentials never reach disk: the archive replaces the real handshake with
a synthetic ``none``-auth one -- real greeting, ``none``-only security list,
real session from ServerInit on -- so whatever the server demanded, and
whatever you typed, is absent, not zeroed. That's also why a capture
replays anywhere: its session never had a password.

Stripping needs knowing where the auth exchange ends. vncdotool follows
``none``, VNC authentication, and ARD / Apple Screen Sharing, not
``tight``, ``vencrypt``, ``rsa-aes``, or UltraVNC's MS-Logon; anything else
aborts the capture rather than guess, with an error explaining the
override.

``meta.json`` still records the offered and negotiated security types and
protocol version -- evidence about the server, not a secret.

Capturing the handshake anyway
--------------------------------

``vnclog --capture-raw-unsafe`` records the handshake verbatim instead --
every auth type alike, credential exchange included. Two reasons to want it:
an auth type vncdotool cannot follow, and a bug that lives in the negotiation
itself. ARD is the second kind: its Diffie-Hellman values are public by
construction and ARD compatibility bugs live in them, but a ``none``
handshake has nowhere to put them, so stripping takes them with everything
else.

.. warning::

   This writes your credential exchange into the archive verbatim. Some of
   these are attackable offline -- ARD's 512-bit Diffie-Hellman is within
   reach of ordinary compute today. Use a **disposable password and rotate it
   afterwards.**

What is **not** stripped
--------------------------

Stripping stops at the end of the handshake. Everything the session carries
is recorded as sent: screen contents, clipboard text, and every keystroke --
including anything typed into a password field *inside* the remote desktop.

So reproduce the bug and nothing else. Do not type a password into the
remote desktop while capturing.

Replaying a capture
---------------------

``vncdo-replay`` serves a capture back at a real VNC client, so a bug against
a server nobody else can run becomes reproducible on a laptop. It is two
commands, because serving the bytes and driving the session are two jobs::

    vncdo-replay --server ./my-bug-capture.zip     # one terminal
    vncdo-replay ./my-bug-capture.zip              # another

The second runs the archive's own ``session.vdo`` -- the events the original
client sent, in the order it sent them. Being faithful to those is the point:
a replay driven by different events is a different session, and a replay of a
different session is not evidence. It connects to ``127.0.0.1::5999``, the
address ``--server`` listens on, unless ``-s`` says otherwise.

Trailing arguments are ``vncdo`` commands appended to the recorded ones, so
this replays the session and then takes a screenshot of where it ended up::

    vncdo-replay ./my-bug-capture.zip capture screen.png

Nothing about the client side is privileged. A GUI viewer pointed at
``127.0.0.1::5999`` works just as well, as does a hand-written ``vncdo``
line. No password: the archive's handshake is a ``none``-auth one.

Waiting for the client
~~~~~~~~~~~~~~~~~~~~~~~~

The handshake is a conversation: the client replies partway through, and what
it says next depends on what it was sent. So it goes out a step at a time,
against the client's real replies, using the same handshake grammar the
capture side uses -- which is what keeps the two from drifting apart.

``meta.json`` also records the protocol version the original session
negotiated, and ``--server`` holds the client to it: a client whose version
reply differs from the recorded one is refused, with an error, and the
connection closed. An archive with no ``meta.json`` is served best-effort,
without that check.

Past ServerInit the recorded framebuffer waits for the client's first
FramebufferUpdateRequest. A capture holds one finite recording of the screen,
so those bytes get exactly one chance to be useful: sent before the client
asked, they go past a client that asks a moment later, which then waits
forever for an update that has already been and gone.

Once the recording runs out the connection is left open. The original server
hung up because its client did, and hanging up here instead would cut short
whatever the live client is still doing with the bytes it has.

If the client goes quiet, ``--server`` warns rather than sitting silent;
``--client-timeout 0`` turns that warning off.

What replay cannot reproduce
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A capture is a recording, not a server. It answers the questions the original
session happened to ask, and nothing else: scroll somewhere the original
never scrolled and there are no bytes for it.

A ``--capture-raw-unsafe`` archive keeps its original handshake, so it is
served verbatim and only suits a client configured the way the original one
was -- the same password, the same security type. Client mode takes ``-p
PASSWORD`` for exactly this case, when the preserved handshake demands one.
It also replays whatever credentials that exchange carried, which is why
``--server`` binds to ``127.0.0.1``. Pass ``--bind`` only for a capture you
know carries nothing sensitive.

Pacing still needs a grammar for the archive's auth type. One negotiating
``tight``, ``vencrypt``, ``rsa-aes``, or MS-Logon can't be paced against the
client's replies, so ``--server`` falls back to serving it unpaced, with a
warning.
