# Task

Audit the prose below. Classify EACH block: **delete**, **rewrite**, or
**keep**. Where you say rewrite, write the replacement text out in full. Give
one line of reasoning per block, then a count by verdict.

## Repo conventions (from CLAUDE.md)

Comment what is surprising and particular to this code. Rationale for
non-obvious choices goes in the commit body, not the code.

## Context

`specs/decoder-architecture.md` is a design document in this repo. It contains
a numbered requirements list whose entries are labelled `R1`, `R2`, `N1`, `N2`.
The labels appear nowhere else in the repo and are not part of any published
standard. A reader of the files below has not opened that document.

## Block 1 --- specs/decoder-architecture.md, in a later section of the same file

```markdown
R1's zero-line `rfb.py` diff is possible because registering an encoding is a
module beside this one plus an entry in `DECODERS`.
```

## Block 2 --- benchmark.py module docstring

```python
"""Time a decoder against a committed golden fixture. No Twisted in the loop.

N1: Raw is the only encoding in live use, so it is the only encoding with a
committed golden.
"""
```

## Block 3 --- decoders.py module docstring

```python
"""Adding an encoding is a module beside this one plus an entry in DECODERS;
rfb.py is not told the encoding exists. specs/decoder-architecture.md.
"""
```

## Block 4 --- rfb.py

```python
    def _readRectangleHeader(self, block):
        # A rectangle's dimensions are u16, so this bounds nothing on its own;
        # the guard is against a server that sends a rectangle larger than the
        # framebuffer it announced, which the u16 range permits.
        if w > MAX_RECT_DIM or h > MAX_RECT_DIM:
            raise ValueError("rectangle larger than framebuffer")
```
