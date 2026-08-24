# Task

Audit the comments and docstrings below. Classify EACH block: **delete**,
**rewrite**, or **keep**. Where you say rewrite, write the replacement out in
full. One line of reasoning per block, then a count by verdict.

## Repo conventions (from CLAUDE.md)

Comment what is surprising and particular to this code. Rationale for
non-obvious choices goes in the commit body, not the code. None of the modules
below are pulled into generated API documentation.

## Context

Every block was written in the branch under review, by the same author, in the
last hour. The commit body for that branch already explains why the pump keeps
the buffer and why `wholeRectangle` is resolved once.

## Block 1 --- rfb.py

```python
        if isinstance(decoder, decoders.PixelDecoder):
            # A decoder's wholeRectangle support is fixed for its class, not
            # decided per rectangle, so the branch is resolved once here at
            # wire-up time rather than on every rectangle that arrives.
            return self._pumpWholeRectangle if decoder.wholeRectangle else self._pumpPixels
```

## Block 2 --- rfb.py

```python
        if x == 0 and y == 0 and w == self.width and h == self.height:
            # Covering the buffer exactly already proves the write is in
            # bounds, so the per-row clip that the general path applies would
            # re-derive a bound the caller has just established.
            self._blitWhole(data)
```

## Block 3 --- decoders.py

```python
    def drive(self, decoder, expect):
        """Drive one decoder against `expect` until it stops.

        Shapes are told apart by the methods they carry: `isinstance` against
        a runtime-checkable Protocol also only checks method names, and every
        PixelDecoder would satisfy ClientDecoder that way.
        """
```

## Block 4 --- rfb.py

```python
    def dataReceived(self, data: bytes) -> None:
        # ~ sys.stdout.write(repr(data) + '\n')
        self._buffer += data
        self._pump()
```

## Block 5 --- rfb.py

```python
    def _pumpFor(self, decoder: decoders.Decoder) -> Callable[..., None]:
        # Called once per decoder at connect time, not per rectangle -- see
        # the discussion on #444. The cost is paid at wire-up, so the
        # per-rectangle path stays a single attribute lookup and there is no
        # dispatch to repeat while a framebuffer update is being drained.
        ...
```
