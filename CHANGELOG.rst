1.3.0 (UNRELEASED)
----------------------
  - Fix functional test suite (@phahn)

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
