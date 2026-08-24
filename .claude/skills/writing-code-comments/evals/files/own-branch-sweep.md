# Task

You wrote every comment below, in this branch, within the last hour, and you
are about to commit. Sweep them. Classify EACH block: **delete**, **rewrite**,
or **keep**. Where you say rewrite, write the replacement out in full. For each
block you keep, state in a handful of words the fact it carries. Then a count
by verdict.

## Repo conventions (from CLAUDE.md)

Comment what is surprising and particular to this code. Rationale for
non-obvious choices goes in the commit body, not the code.

## Context

The commit you are about to write has this body:

> api: disconnect() after a failed command, not just success
>
> `addBoth` runs the disconnector on both the callback and errback path, so a
> command that raised no longer leaves the reactor thread holding an open
> connection. The disconnector ignores its argument because addBoth hands it
> either the result or the Failure, and neither is used.
>
> Binding `protocol` to a local first was how the previous version reached the
> protocol from inside the closure; `self.protocol` is reachable there too and
> the local is dropped.

## Block 1 --- vncdotool/api.py

```python
        def disconnector(_: Any) -> None:
            # The argument is unused on purpose: addBoth passes whatever the
            # deferred carried, either the result or the Failure, and this
            # path needs neither.
            self.protocol.transport.loseConnection()
```

## Block 2 --- vncdotool/api.py

```python
        # addBoth rather than addCallback, so a command that raised still
        # disconnects.
        d.addBoth(disconnector)
```

## Block 3 --- vncdotool/api.py

```python
    def disconnect(self) -> None:
        # The reactor runs in a daemon thread and cannot be restarted, so a
        # second connect() in the same process reuses this reactor rather
        # than starting one.
        self._factory.deferred = None
```

## Block 4 --- vncdotool/api.py

```python
        # Bind the protocol to a local so the closure below can reach it.
        protocol = self.protocol
```
