2.0.0.dev0 (UNRELEASED)
----------------------
  - Fix ``VNCLoggingServerProxy.connectionLost`` rejecting the no-argument call ``Protocol.connectionLost`` promises callers (@sibson)
  - Dependency resolution ignores releases younger than a week, so a compromised upload has to survive public scrutiny before it can reach a build here (@sibson)
  - CI installs from the committed ``uv.lock`` and fails if it is stale, rather than silently resolving something else; ``uv.lock`` is no longer listed in ``.gitignore``, where it had no effect anyway (@sibson)
  - ``--encodings hextile`` offers Hextile, which sends less than Raw on ordinary screen content (@sibson)
  - Add ``vncdo --encodings LIST``, choosing which encodings to offer the server (@sibson, #167, #168)
  - Fix CoRRE decoding (@sibson)
  - Fix CopyRect leaving the screen unchanged (@sibson)
  - Malformed or oversized pixel data now ends the session with a reported error instead of waiting for bytes that never arrive (@sibson)
  - [BREAKING] ``RFBClient.updateRectangle`` takes the ``PixelFormat`` its bytes are in, and is called once per rectangle; ``fillRectangle`` is no longer called for any migrated encoding. Subclasses overriding either have been warned since 1.4.1, see #385 (@sibson)
  - Add ``vncdo --pixel-format FORMAT``, asking the server for ``bgrx8888``, ``rgbx8888``, or ``rgb565`` instead of accepting the format it announces (@sibson)
  - Any byte-aligned truecolor pixel format the server announces can now be captured, not just the five formats vncdotool used to recognize (@sibson)
  - Add ``make typecheck``, running mypy over ``vncdotool`` and ``tests`` (@sibson, #401)
  - ``vncdo`` failures print to stderr as plain messages (@sibson, #395)
  - ``vncdo -v`` logs the pixel format it requests, beside the native format it already logged (@sibson, #394)
  - Drop the per-rectangle debug trace: never used to diagnose anything, and decoding a full-screen update is 30% faster without it (@sibson)
  - Fix screenshots shifted against any server whose first rectangle does not start at (0, 0) (@sibson)
  - Fix ``VMWareClient`` raising ``AttributeError`` instead of detecting the VMware single-pixel update it exists to filter (@sibson, #400)
  - ``PixelFormat`` moves to ``vncdotool.pixelformat``; ``vncdotool.rfb.PixelFormat`` still imports (@sibson, #415)
  - [BREAKING] ``VNCDoToolClient.image_mode`` is gone; its ``FutureWarning`` shipped in 1.4, see #385 (@sibson)
  - A server that announces an unreadable pixel format is now asked for ``rgbx8888`` even when it identifies as Apple Remote Desktop (RFB 3.889); the previous ``rgb565`` fallback there was never confirmed necessary and never fired against any measured server (@sibson)
  - [BREAKING] ``vncdotool.rfb.Rect`` is gone; annotate rectangles as ``tuple[int, int, int, int]`` (@sibson, #415)
  - Local development moves from Makefile.venv + pip to uv; ``make`` targets run under ``uv run`` (@sibson, #383)
  - Fix ``make release`` tagging an empty version (@sibson, #382)
  - Fix: ``api.ThreadedVNCClientProxy.disconnect()`` hanging forever after a failed command (e.g. ``captureScreen`` to a missing directory) left the client's deferred errored, so ``disconnect()``'s success-only callback never ran (@sibson, #146)
  - Raw rectangles skip the rect-buffer entirely, cutting decode time about 11% on a full-screen update (@sibson)
  - ``--encodings zrle`` offers ZRLE, which sends substantially less than Raw on ordinary screen content (@sibson)

1.4.1 (2026-08-19)
----------------------
  - Start the pluggable-decoders migration (see ``specs/decoder-architecture.md``): subclassing ``RFBClient.fillRectangle`` or ``RFBClient.updateRectangle``, or reading/writing ``VNCDoToolClient.image_mode``, now raises a ``FutureWarning``, since both contracts will change once decoders move out of ``rfb.py``. No behavior changes yet; comment on #385 if you rely on either (@sibson, #385)

1.4.0 (2026-08-19)
----------------------
  - Fix: ``api.connect()`` now hands the connection setup to the reactor thread rather than running it on the calling thread. Previously DNS resolution and connector setup ran on the application thread, reaching into reactor internals from outside the reactor (@sibson, #192)
  - Fix black screen captures from servers that announce DesktopSize before sending pixel data, e.g. TightVNC (@sibson, #90)
  - Fix the dead protocol reference in the published ``rfb`` module documentation, which pointed at a RealVNC PDF that has been 403 for years; RFC 6143 and the rfbproto community document replace it (@sibson)
  - Declare python_requires >=3.10, matching the versions CI tests and the development requirements. 3.9 was advertised but neither tested nor able to install the dev environment (@sibson, #357)
  - [BREAKING] vncdo exit codes now say what went wrong: single digits for bad input, including 3 for authentication, and tens grouped by cause out on the wire, 10s connection, 20s protocol, 30s command, 40s timeout, documented in docs/usage.rst.  Scripts reading the exit code see new values: authentication failure is now 3 and a session cut short 11, both of which used to be 0; an unknown action is now 2, previously 1 (@sibson, #345)
  - Fix: vncdo reports failure instead of success when the connection closes before the requested commands finish, including on VNC authentication failure (@sibson, #345)
  - Fix: vncdo reports the error and exits non-zero when a command fails, rather than hanging (@sibson, #345)
  - Protocol errors abort the session instead of only being logged, reported through the new ``RFBClient.vncProtocolError`` hook (@sibson, #345)
  - Add ``vnclog --capture-raw FILE.zip``, an upload-ready wire capture for filing bugs against servers we can't host. The auth exchange is stripped rather than redacted, so the archive holds no credential bytes and replays without a password; ``--capture-raw-unsafe`` records the handshake whole. See docs/capture.rst (@sibson, #352)
  - Add ``vncdo-replay``, serving a capture back at a real client (``--server``) or running the session recorded inside it (@sibson, #352)
  - Add ``vnclog --one-shot``, serving a single session then exiting; implied
    by ``--capture-raw``
  - [BREAKING] ``vnclog --forever`` is renamed ``--file-per-client``. It never
    controlled how long vnclog ran -- vnclog has always accepted connections
    until stopped -- it selects a separate ``.vdo`` per client connection.
    Scripts passing ``--forever`` must be updated
  - ``vnclog`` no longer drops a session when its own logging fails to parse a
    message: the semantic log is an observer, and a server the real client
    copes with should not be cut off by the proxy
  - Fix ``vnclog`` desyncing against RFB 3.7+ servers using VNC password
    authentication (it ate the 16-byte auth response instead of skipping it,
    then lost track of the client message stream entirely) (@sibson, #272)

1.3.0 (2026-04-03)
----------------------
  - Fix functional test suite (@phahn)
  - Python 3.12 is supported, Python 3.7 support removed (@phahn)
  - Improve documentation (@phahn)
  - Improve PEP-484 type hinting (@phahn)
  - Fix mouse dragging (@phahn)
  - Improve special key handling, fix key-down/key-up discrepancy with force_caps (@phahn, #270)
  - Allow specifying a format with captureScreen (@erjiang, #293)
  - Allow input literal ``-`` via ``client.keyPress`` with ``minus`` keyword (#302)
  - Fix: typefile and pastefile now accept ``-`` as filename for stdin (#307)
  - Switch from pycryptodomex to cryptography.io (@geofft, #278)
  - Remove transitive dependency zope.interface (#298)
  - Bump minimum Pillow version to 10.0.1 (#312)

1.2.0 (2023-06-06)
----------------------
  - fixes for api.shutdown and disconnect raise exceptions, #256

1.1.0 (2023-04-01)
----------------------
Huge thanks to @pmhahn for single handedly driving conversion to modern Python3, as well
as cleaning up a ton of outstanding issues.

  - [BREAKING] drop python 2.x support, thanks @pmhahn
  - Use built-in Unittest and mock for testing
  - PEP-484 type hinting, thanks @pmhahn
  - Doc improvements, thanks @luke-jr, @pmhahn, @samiraguiar
  - Test for byte handling, thanks @ponty, refs #177
  - Internal implementation of DES replaced by PyCrotodomeX

  - Support for Apple Remote Desktop (ARD), thanks @andywgrant, @pmhahn
  - Support for pseudo-encoding LastRec, thanks @pmhahn
  - Support for Extended QEMU Key Events, thanks @pmhahn
  - Support IPv6 addresses for server connection, thanks @pmhahn

  - Bugfix, use configured log outputs over stdout, thanks @pevogam
  - Bugfix, handle invalid password, thanks @dozysun
  - Bugfixes for loggingproxy, thanks @joachimmetz, @pmhahn, @guicho271828


1.0.0 (2020-04-10)
----------------------
  - add ZRLE encoding, thanks Adrian Weiler
  - drop python2 support
  - fix mouseDrag behaviour, thanks Samir Aguiar

0.13.0 (2019-11-21)
----------------------
  - new flag --incremental-refreshes, increased compatibility of capture, thanks Amir Rossert
  - exit non-zero and print to stderr for unknown commands, thanks Amir Rossert

0.12.1 (2018-12-06)
----------------------
   - bugfix expectRegion to use cropped images for compare, thanks Michael Fürnschuß
   - direct support for building RPMs, thanks Plamen Dimitrov

0.12.0 (2018-04-07)
----------------------
  - connect via UNIX sockets, thanks Matteo Cafasso
  - bugfix, XTightVNC initial connection, thanks Antti Kervinen

0.11.2 (2017-09-24)
----------------------
  - fix version metadata, thanks Kevin Gottsman

0.11.1 (2017-07-23)
----------------------
  - add api.client.disconnect()
  - fix python2.x compatibility, thanks Ostrosablin Vitaly

0.11.0 (2017-06-09)
---------------------
  - enable PSEUDO_DESKTOP_SIZE_ENCODING by default to allow desktop resizing, thanks rebasegod
  - python 3.0 support, thanks jamtwister
  - added pastefile command, thanks Rogan Dawes
  - debian packaging improvements, thanks Alexander Kläser
  - fix loggingproxy, thanks Matthias Weckbecker

0.10.0 (2016-03-03)
---------------------
  - drop official 2.6 support, it'll probably work for a while still
  - use frombytes rather than fromstring for compatibility with PIL
  - vnclog works with password protected servers using --password-required
  - exit more reliably after an error
  - use increatmental frameBufferUpdateRequests, appears to be compatible with more servers
  - include basic version negotiation with servers, thanks Ezra Bühler

0.9.0 (2015-05-08)
------------------
  - add special keys [~!@#$%^&*()_+{}|:\"<>?] to --force-caps, for servers that don't handle them, Tyler Oderkirk, Aragats Amirkhanyan
  - improve vnclog performance with TCP_NODELAY, Ian Britten
  - by default pause 10ms between sending commands, better compatibility with servers
  - better handle screen resizing, Daniel Stelter-Gliese
  - API, fix deadlocks due to threaded init of PIL, thanks Antti Kervinen
  - API, support password protected server, thanks Antti Kervinen
  - API, able to connect to multiple servers, Daniel Stelter-Gliese
  - drop official support for py2.4 and py2.5
  - use Pillow rather than PIL

Thanks to Jan Sedlák, Daniel Stelter-Gliese, Antti Kervinen, Anatoly Techtonik, Tyler Oderkirk and Aragats Amirkhanyan for helping make this release possible

0.8.0 (2013-08-06)
------------------
  - improved documentation using sphinx
  - regional capture and expect that operate on a portion of the display
  - --force-caps, better compatibility when sending UPPERCASE to servers
  - --timeout, exit with an error after a given number of seconds
  - experimental synchronous API for easier integration with non-Twisted apps

0.3.0 (2012-12-22)
------------------
  - main program renamed to vncdo, vncdotool continues an alias for now
  - use host:display, host::port syntax like other vnc tools, removed -d
  - read/play commands from stdin or file
  - vnclog, creates scripts from captured interactive sessions
  - better control over mouse in screen captures with --nocursor
    and --localcursor
  - mousemove, sleep command aliases to match xdotool
  - keyup/keydown commands for more control over keypresses
  - send SetEncodings on connect, thanks Matias Suarez for fix
  - debian packaging
  - type "Hello World" now preserves capitalization
  - basic compatibility with VNC 4.0 servers, found in some KVMs
  - improved frameUpdate handling
  - --warp to replay script faster than real-time
  - --delay, insert a delay between sending commands

0.2.0 (2012-08-07)
--------------------------------
  - add pause, mouseup, mousedown, drag commands
  - only require Twisted 11.1.0, so we can have py2.4 support
  - bugfixes, thanks Christopher Holm for reporting
     - vncdotool type -something now works
     - no longer silently fail for unsupported image formats

0.1.1 (2011-05-18)
--------------------------------
  - add PIL to requires
  - fix bug where incorrect mouse button is sent

0.1.0 (2011-03-03)
--------------------------------
  - first release
  - commands: press, type, move, click, capture, expect
