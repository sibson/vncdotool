# Task

Below are four proposed `CHANGELOG.rst` entries for the same release. For each,
give a verdict of **keep as written** or **cut**, and where you cut, write the
entry you would commit instead. Then a count by verdict.

## Repo conventions (from CLAUDE.md)

> Every user-visible fix gets a `CHANGELOG.rst` entry under the current
> `(UNRELEASED)` heading, in the form `- <description> (@author, #NNN)`.
>
> Rationale for non-obvious choices goes in the commit body, not left as
> conversation context.

## Context

The changelog is read by someone scanning a release to decide whether it
affects them. Each entry below already has a commit whose body carries the
full mechanism.

## Entry 1

> - ``vncdo`` failures now read as CLI errors: the message goes to stderr on
>   its own, instead of being rendered as ``CRITICAL:root:<message>`` by the
>   logging module. The failure's traceback moved to ``-vv``, and log records
>   no longer carry the ``:root:`` logger name. Exit statuses are unchanged.
>   (@sibson, #395)

## Entry 2

> - ``--localcursor`` now draws the pointer client-side. Previously
>   ``RFBClient`` requested the Cursor pseudo-encoding but discarded the
>   rectangle, because ``updateCursor`` was never wired to the blit path. The
>   fix routes it through ``ControlDecoder``. (@sibson, #442)

## Entry 3

> - ``api.connect()`` disconnects after a failed command, not only after a
>   successful one (@sibson, #428)

## Entry 4

> - The ``--encodings`` flag now rejects an unknown encoding name instead of
>   silently negotiating without it. Scripts passing a misspelled name will
>   now exit non-zero; correct the name or drop the flag. (@sibson, #405)
