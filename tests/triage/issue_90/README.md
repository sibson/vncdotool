# Issue #90 wire-level reproduction — TRIAGE ARTIFACT

Temporary evidence attached to https://github.com/sibson/vncdotool/issues/90.
Delete this directory when the fix lands (see `tests/unit/test_issue_90.py`).

`fake_tightvnc.py` is a minimal RFB 3.3 server that replays the behaviour the
issue's `-v` logs show for TightVNC on Windows: the first (non-incremental)
FramebufferUpdateRequest is answered with a FramebufferUpdate containing only
the DesktopSize pseudo-rectangle (-223) — geometry, no pixels — and the real
RAW frame follows ~150 ms later. `--pixels-first` makes it answer the first
request with pixel data directly, the way libvncserver does.

All runs use the real `vncdo` CLI over real TCP:

| Artifact | Command | Result |
|---|---|---|
| `fail.png`, `vncdo_fail.log`, `server_fail.log` | `vncdo -v -s 127.0.0.1::5999 capture fail.png` vs TightVNC behaviour | all-black 1024x640; server log shows it could not deliver the pixel frame: client already disconnected |
| `ok.png`, `vncdo_ok.log`, `server_ok.log` | same, vs `--pixels-first` | correct test pattern — only the update ordering differs |
| `libvnc.png`, `vncdo_libvnc.log` | same, vs libvncserver's `example` server (`make libvnc-examples`) | correct capture from a real server |
| `twice_1st.png`, `twice_2nd.png`, `vncdo_twice.log`, `server_twice.log` | `vncdo -v ... capture a.png capture b.png` vs TightVNC behaviour | first capture black, second correct — the workaround reported in the thread in 2018 |

Regenerate with:

```
python3 tests/triage/issue_90/fake_tightvnc.py --port 5999 --once &
vncdo -v -s 127.0.0.1::5999 capture fail.png
```
