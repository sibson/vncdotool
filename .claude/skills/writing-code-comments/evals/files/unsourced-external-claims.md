# Task

Audit the comments and documentation below. Classify EACH block: **delete**,
**rewrite**, or **keep**. Where you say rewrite, write the replacement out in
full. One line of reasoning per block, then a count by verdict.

## Repo conventions (from CLAUDE.md)

Comment what is surprising and particular to this code. Check the protocol
documents before writing anything that describes the wire: guessing a
behaviour from the surrounding code produces something that works against one
server and no other.

## Context

Blocks 1, 2 and 3 have nothing behind them: no test, no captured session, no
spec citation. The author wrote each while reading the code. RFC 6143 and the
community `rfbproto` document are the protocol references this repo uses, and
neither states any of those three claims.

Block 4 is different. The truncation it describes was hit and recorded against
the x11vnc 0.9.16 container in `tests/servers/docker-compose.yml`, and the
comment says so. Take its stated observation at face value.

## Block 1 --- tests/functional/test_encodings.py

```python
    def test_corre_falls_back(self):
        # tigervnc answers a request for CoRRE with Raw, so this scenario
        # exercises the Raw path even though it asked for CoRRE.
        self.run_scenario("corre", server="tigervnc")
```

## Block 2 --- docs/options.rst

```rst
``--localcursor``
   Some servers don't draw the mouse pointer into the framebuffer themselves,
   so without this the pointer is invisible in captured screenshots.
```

## Block 3 --- vncdotool/client.py

```python
    def _sendKeyEvent(self, key, down):
        # UltraVNC drops key events that arrive within 10ms of each other, so
        # the caller must pace them.
        self.transport.write(pack("!BBxxI", 4, down, key))
```

## Block 4 --- vncdotool/rfb.py

```python
    def _handleServerCutText(self, block):
        # As observed against x11vnc 0.9.16 on the test fleet, the length
        # field counts bytes, not characters, and a UTF-8 clipboard therefore
        # arrives truncated mid-codepoint.
        length = unpack("!I", block[4:8])[0]
```
