# Command Reference

A `vncdo` invocation is a list of commands, run in order against one
connection. Each command consumes the arguments that follow it, so several
can be written on a single line:

```
> vncdo move 100 100 click 1 type hello key enter
```

`--delay MILLISECONDS` pauses between commands, and between the individual
keypresses of `type` and `typefile`. `--warp FACTOR` divides the
duration of every `pause`. A command that fails ends the session at that
point; see [the exit status table](usage.md#exit-status) for what the codes mean.

## capture FILENAME

Save the whole screen to FILENAME. The extension chooses the image format
and must be one of `png`, `jpg`, `jpeg`, `gif` or `bmp`; anything
else is rejected before connecting, exit 2. A path that cannot be written
exits 30. Needs [Pillow](https://pillow.readthedocs.io/).

## click BUTTON

Press and release mouse BUTTON, a number from 1, at the pointer's current
position. The position is whatever a previous `move` set, and starts at
(0, 0): a `click` with no `move` before it clicks the top-left corner.

## drag X Y

Move the pointer to X,Y one pixel at a time, pausing 0.2 seconds between
steps, so a server sees a drag rather than a jump. The pause is not scaled by
`--warp`, so a long drag takes a long time -- 200 pixels is 40 seconds.

## expect FILENAME [FUZZ]

Wait until the screen matches the image in FILENAME. Only screens the same
size as the image can match.

FUZZ is how far any one pixel may sit from the target, a whole number from 0
(exact, the common case) to 255, measured as a perceived color difference
where 255 is the furthest two pixels can be apart. Left out, the bound is
whatever the negotiated pixel format cannot express, so a server sending
5-bit red is not waited on to reproduce an 8-bit value. `--expect-fuzz`
sets the same bound for every `expect`. A FUZZ that is not a whole number
in 0..255 exits 2; a trailing argument that is not a number at all is read as
the next command rather than reported.

Without `--timeout` a screen that never matches waits forever; with one,
the wait ends at `TIMEOUT` seconds, exit 40. A target image larger than
the screen can never match and fails immediately, exit 30. Needs [Pillow](https://pillow.readthedocs.io/).

## key KEY

Press and release KEY. A single character is sent as itself; longer names
come from the keysym table -- `enter`, `tab`, `del`, `f1`. `-`
joins modifiers to a key: `ctrl-c`, `shift-a`, `ctrl-alt-del`.

Because `-` is the separator, a hyphen as part of a combination has to be
written `minus`: `key -` sends a hyphen, but `key ctrl--` is an error
and `key ctrl-minus` is what to write. An unrecognised name is not
reported; each part of it is sent as a literal character.

`--force-caps` sends capitals as `shift-LETTER`, for servers that
otherwise type them lowercase.

## keydown KEY, kdown KEY

Press KEY and leave it held. Nothing releases it but a matching `keyup`
or the end of the session, so a held modifier applies to every command after
it. `kdown` is an alias.

## keyup KEY, kup KEY

Release KEY. Releasing a key that was never pressed is sent to the server
like any other event, and most servers ignore it. `kup` is an alias.

## mousedown BUTTON, mdown BUTTON

Press mouse BUTTON at the current position and leave it held, for dragging or
for chording with `drag`. `mdown` is an alias.

## mouseup BUTTON, mup BUTTON

Release mouse BUTTON at the current position. `mup` is an alias.

## move X Y, mousemove X Y

Move the pointer to X,Y in one step. This is the position `click`,
`mousedown`, `mouseup` and `drag` work from. `mousemove` is an alias.

## pastefile FILENAME

Send the contents of FILENAME to the server's clipboard in one message,
rather than as keypresses -- much faster than `typefile` for a large body of
text, and it needs the far side to paste. CRLF line endings are converted to
LF. The text is encoded Latin-1, as RFB requires, so a character outside it
fails. `-` reads from stdin. A server is free to ignore the message, and
nothing reports that it did.

## pause SECONDS, sleep SECONDS

Wait SECONDS, which may be fractional, before the next command. `--warp
FACTOR` divides it, so `--warp 2` halves every pause in a script.
`sleep` is an alias.

## rcapture FILENAME X Y W H

Save the W by H region of the screen at X,Y to FILENAME. Formats and write
failures are as for `capture`. The region must lie on the screen: one that
runs off an edge, or that a mid-session desktop resize leaves off the screen,
fails with a message naming the region and the screen size, exit 30. Needs
[Pillow](https://pillow.readthedocs.io/).

## rexpect FILENAME X Y [FUZZ]

Wait until the region of the screen at X,Y matches the image in FILENAME.
The region is the size of that image, so only X and Y are given. FUZZ, the
default bound and the timeout behaviour are as for `expect`, and an
off-screen region fails as for `rcapture`, exit 30. Needs [Pillow](https://pillow.readthedocs.io/).

## rstable SECONDS X Y W H [FUZZ]

Wait until the W by H region of the screen at X,Y stops changing. SECONDS,
FUZZ and the timeout behaviour are as for `stable`, and an off-screen
region fails as for `rcapture`, exit 30. Needs [Pillow](https://pillow.readthedocs.io/).

Waiting on a region is the way past a server that never goes quiet: exclude
the clock or the blinking cursor, and the rest of the screen can settle.

## stable SECONDS [FUZZ]

Wait until the screen has gone SECONDS without changing. Each framebuffer
update is compared against the one before it, and one that differs by more
than FUZZ starts the wait again.

FUZZ uses the same scale and default as `expect`, measured here between
successive frames rather than against a file; `--expect-fuzz` and
`--expect-blur` apply to both.

The wait takes at least SECONDS, because the absence of a change cannot be
observed before the window has passed, and longer whenever a late update
restarts it. A screen that changes more often than that never settles: with
`--timeout` the run ends at `TIMEOUT` seconds, exit 40, and without one it
waits forever. Needs [Pillow](https://pillow.readthedocs.io/).

## type TEXT

Send TEXT as one keypress per character, with `--delay` between them. Only
characters that stand for themselves are sent: there is no way to write a
newline or a tab, and a literal `-` is sent as `minus`. Use `key` for
anything else, or `typefile` for text that has line breaks in it.

## typefile FILENAME

Type out the contents of FILENAME as keypresses, as `type` does, with
`--delay` between them. Newlines are sent as `enter`, tabs as `tab`,
`-` as `minus`, and carriage returns are dropped, so a CRLF file types the
same as an LF one. `-` reads from stdin. Slow for anything large;
`pastefile` sends the same text in one message.

## Reading commands from a file or stdin

An argument in command position that names an existing file is read as
commands and spliced in where it appeared, so a script can be mixed with
commands on the same line:

```
> vncdo login.vdo capture after-login.png
```

The file is split like a shell command line: quotes group an argument, and
`#` begins a comment that runs to the end of the line. Line breaks are
whitespace, so a script may be written one command per line or all on one.

A lone `-` reads commands from stdin instead:

```
> echo "type hello key enter" | vncdo -
```

This only works when `-` is the whole command list; elsewhere it is treated
as a filename or a command and fails, exit 2.
