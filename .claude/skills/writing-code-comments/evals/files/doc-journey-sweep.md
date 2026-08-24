# Task

Audit the documentation passages below. Classify EACH block: **delete**,
**rewrite**, or **keep**. Where you say rewrite, write the replacement out in
full — including any heading you would change. One line of reasoning per
block, then a count by verdict.

## Repo conventions (from CLAUDE.md)

Rationale for non-obvious choices goes in the commit body, not left as
conversation context. Findings outside the diff get a line and a pointer, not
a section.

## Context

`specs/decoder-architecture.md` is a design document that ships in the repo. It
is read by someone about to add an encoding. Every passage below was added in
the branch under review, alongside the code it describes, and the branch's
commit bodies already carry the investigation that produced the design.

## Block 1 --- section heading and its opening sentence

```markdown
### A decoder that is only pixels does not need the machinery

It is one optional method with a `None` default, not a second architecture.
```

## Block 2

```markdown
Whether a decoder ever answers `wholeRectangle` is fixed for the class, not
per rectangle, so it is resolved the same place and the same way the
per-decoder pump callable is resolved: once, at wire-up.
```

## Block 3

```markdown
Decoders depend on nothing from `rfb.py`: the pump internals — `_rectBuffer`,
`_pumpPixels`, `_pumpWholeRectangle` and `_pumpForClient` — now live with the
pump rather than on the decoder, where they used to sit.
```

## Block 4

```markdown
| Protocol | consumes | effect | method | encodings |
|---|---|---|---|---|
| `PixelDecoder` | bytes | fills a `RectBuffer` | `decodePixels` | Raw, RRE, CoRRE, Hextile, ZRLE, Tight |
| `ClientDecoder` | bytes | calls a client method | `decodeForClient` | CopyRect, Cursor |
```

## Block 5

```markdown
Per-encoding decode tests get one file per decoder, `test_decoder_<name>.py`,
so a failure names the encoding in its test id rather than hiding it inside a
combined module.
```
