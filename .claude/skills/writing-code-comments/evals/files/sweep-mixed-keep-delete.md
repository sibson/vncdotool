# Task

Audit the comments in this diff. Classify EACH comment block below:
**delete**, **rewrite**, or **keep**.

Give your verdict per block, one line of reasoning each. Then a count by verdict.

## Repo conventions (from CONTRIBUTING)

Comment what is surprising and particular to this code. Do not comment what the
reader can look up, infer from a name, or learn by running it.

## Context

This project has no convention routing rationale to commit messages. The commits
below are the entire history of these lines.

Block 1 was introduced by commit `4f21a0c`, whose full message is:

> proxy: forward SetEncodings to the upstream server
>
> Adds the passthrough so recorded sessions negotiate the same encodings the
> real client asked for.

Block 2 was introduced by commit `9ce77b1`, whose full message is:

> capture: write frames to the session directory
>
> Uses the run id as the subdirectory name.

## Block 1 --- loggingproxy.py

```python
    def handle_set_encodings(self, encodings):
        # SetEncodings only says what the client asked for, and a server may
        # ignore it. Trust the encoding on each rectangle, not this list.
        self.requested_encodings = encodings
        self.upstream.send_set_encodings(encodings)
```

## Block 2 --- capture.py

```python
    def frame_path(self, run_id, index):
        # Build the path to the frame file from the run id and frame index.
        return self.session_dir / run_id / f"frame-{index:05d}.png"
```

## Block 3 --- decoder.py

```python
    def decode_zrle(self, data, rect):
        # ZRLE assumes 3-byte compressed pixels, so this only works for
        # 32bpp/depth-24/little-endian. Anything else silently decodes wrong
        # rather than raising.
        pixels = self._unpack_cpixels(data)
        return self._blit(pixels, rect)
```
