## 2.0.0.dev0 (UNRELEASED)
- vncdo decodes framebuffer updates through a new pluggable per-encoding architecture (`vncdotool/decoders/`) instead of one monolithic protocol handler. Every encoding besides Raw -- CopyRect, RRE, CoRRE, Hextile, ZRLE and Tight (closes #264) -- is new in this release; a server could never previously reach any of them (`--encodings` didn't exist, #167, #168). Server-to-client messages (`SetColourMapEntries`, `ServerCutText`, `Bell`, `ServerFence`) move to the same per-message-handler pattern (#474)
- [WARNING] `vncdo` offers `tight,hextile,raw` by default instead of Raw alone, lossless but more CPU to decode (`--encodings` still replaces the list). Hextile decodes about 1.5x faster, ZRLE about 12x, Tight palette about 1.3x, and Raw skips the rect-buffer entirely for about 11% more; fixed CoRRE and CopyRect decoding, and a ZRLE palette index past the end of its palette raising `IndexError` instead of a reported error; fixed ZRLE misdecoding against servers, `libvncserver`-based ones among them, that report `depth=32` but narrow CPIXELs to 3 bytes anyway (@sibson, @kudala-bharani, #483)
- Add `vncdo --encodings LIST` to choose which encodings to offer (raw, copyrect, rre, corre, hextile, zrle, tight); Tight JPEG rectangles decode only once `--jpeg-quality LEVEL` asks for them, refusing an unsolicited one instead of decoding it lossily (#167, #168, #264)
- Add `vncdo --pixel-format FORMAT` (`bgrx8888`, `rgbx8888`, `rgb565`); any byte-aligned truecolor format the server announces can now be captured natively. Fixed `expect` never matching at a reduced-depth format such as `rgb565`, an unreadable-format server not falling back to `rgbx8888` when it identifies as Apple Remote Desktop, and `vnclog` garbling its log and `--capture-raw` metadata on a non-native format while masking the real decode failure with an `AttributeError` (`PixelFormat` moves to `vncdotool.pixelformat`, #415)
- Add `vncdo stable SECONDS [FUZZ]` and `rstable SECONDS X Y W H [FUZZ]`, waiting for the screen to settle instead of matching a reference image
- Add `ws://` and `wss://` server addresses to `-s`, reaching a server published through noVNC, websockify, Proxmox or Selenoid without a TCP bridge in front of it; the URL's path and query string are part of the address and are sent as given, and `wss://` always verifies the server certificate against the system trust store. `autobahn` and `Twisted[tls]` are now required rather than optional, so this works from a plain `pip install vncdotool` (#259)
- [BREAKING] `expect`/`rexpect` match pixel by pixel (a 0-255 bound) instead of by the root-mean-square difference of two histograms; `expectScreen`/`expectRegion` take `fuzz`/`blur` in place of `maxrms`. Add `--fuzz`/`--blur` flags for `expect`/`rexpect`/`stable` (fixing a crash when neither command got a fuzz; `--jpeg-quality` turns a blur on automatically). Fixed `rexpect`/`rcapture`/`expect` against an off-screen or oversized region erroring by name instead of writing black pixels or polling until timeout
- Fix `vnclog` hanging forever on pasted clipboard text, dropping QEMU extended key events, stalling on a message split across two reads, and rejecting Twisted's no-argument `connectionLost` call
- Fix Apple Remote Desktop authentication with a non-ASCII username or password, which raised `ValueError` out of the AES encryptor instead of connecting; a credential over 63 bytes as UTF-8 now ends the attempt with a message naming the field, which the protocol's 64-byte fields cannot carry (@sibson)
- Fix session-ending robustness: malformed or oversized server data (a bad header, unknown security/auth type, unrecognized message or encoding, oversized pixel data) now ends the session with a reported error instead of hanging or parsing garbage; a `ServerCutText`/`SetColourMapEntries` above 1 MiB errors instead of buffering unbounded data (#474), as do the RFB 3.8 authentication-failure and connection-failed reason strings (@sibson, #501); `ServerFence` is answered instead of ending the session as unknown (@sibson, based on @TeofilisMartisius's #323); `updateCursor` no longer crashes or leaves a stale cursor on a hide-pointer update (#449); `RFBFactory` no longer raises `AttributeError` on direct ARD authentication; `VMWareClient` no longer raises `AttributeError` instead of filtering its single-pixel update (#400); `api.ThreadedVNCClientProxy.disconnect()` no longer hangs after a failed command (#146)
- Fix any substring of `drag` being accepted as the `drag` command; fix `self.width`/`self.height` staying stale after a server sends `PSEUDO_DESKTOP_SIZE` mid-session; fix screenshots shifted against a server whose first rectangle does not start at (0, 0); `vncdo` failures print to stderr as plain messages, and `-v` logs the pixel format it requests (#394, #395)
- VNC Authentication takes its DES from `cryptography.hazmat.decrepit`, where upstream moved it, rather than the `hazmat.primitives` alias it has been deprecating since 43.0.0 and says it will drop; `cryptography>=43` is now required
- `vncdo`, `vnclog` and `vncdo-replay` parse their arguments with `argparse` instead of the deprecated `optparse`. Where the command list starts is unchanged -- `vncdo move -10 20`, `vncdo -- key a`, and options after the first command all read as before. Two cases do change: a password given as a separate argument that itself looks like an option now needs the attached spelling, `vncdo -p-dash` or `vncdo --password=-dash`; and `vncdo-replay` reads its own options before the archive or after the command list, no longer between the two -- `vncdo-replay -v ARCHIVE CMD`, not `vncdo-replay ARCHIVE -v CMD` (#354)
- [BREAKING] `RFBClient.updateRectangle` takes the `PixelFormat` its bytes are in and is called once per rectangle (`fillRectangle` no longer called for a migrated encoding, warned since 1.4.1, #385); `VNCDoToolClient.image_mode` is gone (warned since 1.4, #385); `vncdotool.rfb.Rect` is gone, annotate rectangles as `tuple[int, int, int, int]` (#415). The `FutureWarning` naming this change now says it happened rather than that it will; #385 stays open through the 2.0 release for anyone it broke

## 1.4.1 (2026-08-19)
- Start the pluggable-decoders migration (see `specs/decoder-architecture.md`): subclassing `RFBClient.fillRectangle` or `RFBClient.updateRectangle`, or reading/writing `VNCDoToolClient.image_mode`, now raises a `FutureWarning`, since both contracts will change once decoders move out of `rfb.py`. No behavior changes yet; comment on #385 if you rely on either (@sibson, #385)

## 1.4.0 (2026-08-19)
- Fix: `api.connect()` now hands the connection setup to the reactor thread rather than running it on the calling thread. Previously DNS resolution and connector setup ran on the application thread, reaching into reactor internals from outside the reactor (@sibson, #192)
- Fix black screen captures from servers that announce DesktopSize before sending pixel data, e.g. TightVNC (@sibson, #90)
- Fix the dead protocol reference in the published `rfb` module documentation, which pointed at a RealVNC PDF that has been 403 for years; RFC 6143 and the rfbproto community document replace it (@sibson)
- Declare python_requires >=3.10, matching the versions CI tests and the development requirements. 3.9 was advertised but neither tested nor able to install the dev environment (@sibson, #357)
- [BREAKING] vncdo exit codes now say what went wrong: single digits for bad input, including 3 for authentication, and tens grouped by cause out on the wire, 10s connection, 20s protocol, 30s command, 40s timeout, documented in docs/usage.rst.  Scripts reading the exit code see new values: authentication failure is now 3 and a session cut short 11, both of which used to be 0; an unknown action is now 2, previously 1 (@sibson, #345)
- Fix: vncdo reports failure instead of success when the connection closes before the requested commands finish, including on VNC authentication failure (@sibson, #345)
- Fix: vncdo reports the error and exits non-zero when a command fails, rather than hanging (@sibson, #345)
- Protocol errors abort the session instead of only being logged, reported through the new `RFBClient.vncProtocolError` hook (@sibson, #345)
- Add `vnclog --capture-raw FILE.zip`, an upload-ready wire capture for filing bugs against servers we can't host. The auth exchange is stripped rather than redacted, so the archive holds no credential bytes and replays without a password; `--capture-raw-unsafe` records the handshake whole. See docs/capture.rst (@sibson, #352)
- Add `vncdo-replay`, serving a capture back at a real client (`--server`) or running the session recorded inside it (@sibson, #352)
- Add `vnclog --one-shot`, serving a single session then exiting; implied
    by `--capture-raw`
- [BREAKING] `vnclog --forever` is renamed `--file-per-client`. It never
    controlled how long vnclog ran -- vnclog has always accepted connections
    until stopped -- it selects a separate `.vdo` per client connection.
    Scripts passing `--forever` must be updated
- `vnclog` no longer drops a session when its own logging fails to parse a
    message: the semantic log is an observer, and a server the real client
    copes with should not be cut off by the proxy
- Fix `vnclog` desyncing against RFB 3.7+ servers using VNC password
    authentication (it ate the 16-byte auth response instead of skipping it,
    then lost track of the client message stream entirely) (@sibson, #272)

## 1.3.0 (2026-04-03)
- Fix functional test suite (@phahn)
- Python 3.12 is supported, Python 3.7 support removed (@phahn)
- Improve documentation (@phahn)
- Improve PEP-484 type hinting (@phahn)
- Fix mouse dragging (@phahn)
- Improve special key handling, fix key-down/key-up discrepancy with force_caps (@phahn, #270)
- Allow specifying a format with captureScreen (@erjiang, #293)
- Allow input literal `-` via `client.keyPress` with `minus` keyword (#302)
- Fix: typefile and pastefile now accept `-` as filename for stdin (#307)
- Switch from pycryptodomex to cryptography.io (@geofft, #278)
- Remove transitive dependency zope.interface (#298)
- Bump minimum Pillow version to 10.0.1 (#312)

## 1.2.0 (2023-06-06)
- fixes for api.shutdown and disconnect raise exceptions, #256

## 1.1.0 (2023-04-01)
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


## 1.0.0 (2020-04-10)
- add ZRLE encoding, thanks Adrian Weiler
- drop python2 support
- fix mouseDrag behaviour, thanks Samir Aguiar

## 0.13.0 (2019-11-21)
- new flag --incremental-refreshes, increased compatibility of capture, thanks Amir Rossert
- exit non-zero and print to stderr for unknown commands, thanks Amir Rossert

## 0.12.1 (2018-12-06)
- bugfix expectRegion to use cropped images for compare, thanks Michael Fürnschuß
- direct support for building RPMs, thanks Plamen Dimitrov

## 0.12.0 (2018-04-07)
- connect via UNIX sockets, thanks Matteo Cafasso
- bugfix, XTightVNC initial connection, thanks Antti Kervinen

## 0.11.2 (2017-09-24)
- fix version metadata, thanks Kevin Gottsman

## 0.11.1 (2017-07-23)
- add api.client.disconnect()
- fix python2.x compatibility, thanks Ostrosablin Vitaly

## 0.11.0 (2017-06-09)
- enable PSEUDO_DESKTOP_SIZE_ENCODING by default to allow desktop resizing, thanks rebasegod
- python 3.0 support, thanks jamtwister
- added pastefile command, thanks Rogan Dawes
- debian packaging improvements, thanks Alexander Kläser
- fix loggingproxy, thanks Matthias Weckbecker

## 0.10.0 (2016-03-03)
- drop official 2.6 support, it'll probably work for a while still
- use frombytes rather than fromstring for compatibility with PIL
- vnclog works with password protected servers using --password-required
- exit more reliably after an error
- use increatmental frameBufferUpdateRequests, appears to be compatible with more servers
- include basic version negotiation with servers, thanks Ezra Bühler

## 0.9.0 (2015-05-08)
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

## 0.8.0 (2013-08-06)
- improved documentation using sphinx
- regional capture and expect that operate on a portion of the display
- --force-caps, better compatibility when sending UPPERCASE to servers
- --timeout, exit with an error after a given number of seconds
- experimental synchronous API for easier integration with non-Twisted apps

## 0.3.0 (2012-12-22)
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

## 0.2.0 (2012-08-07)
- add pause, mouseup, mousedown, drag commands
- only require Twisted 11.1.0, so we can have py2.4 support
- bugfixes, thanks Christopher Holm for reporting
     - vncdotool type -something now works
     - no longer silently fail for unsupported image formats

## 0.1.1 (2011-05-18)
- add PIL to requires
- fix bug where incorrect mouse button is sent

## 0.1.0 (2011-03-03)
- first release
- commands: press, type, move, click, capture, expect
