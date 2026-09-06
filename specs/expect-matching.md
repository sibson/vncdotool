# What `expect` Compares — Design

Status: built, across the five commits under Phasing. Replaced the histogram-RMS
comparison in `VNCDoToolClient._expectMatch` and retired
`tests/goldens/scene-lossy.vdo`.

## Problem

`expect FILE FUZZ` blocks a script until the screen matches FILE. It decides by
comparing *histograms* and thresholding their root-mean-square difference, so
it throws away every spatial relationship in the image before deciding whether
two images are the same. Two failures follow.

It cannot see a small change. An 8x8 pixel patch changing on a 256x192 screen
moves the histogram RMS by 4.9, while re-encoding the same unchanged screen as
a high-quality JPEG moves it by 126. Anything the encoding does swamps
everything the user is waiting for.

It has no usable threshold under a lossy encoding, and none under a reduced
pixel format either. Replaying the committed goldens, the worst correct match
and the nearest wrong scene are:

| fixture | worst correct | nearest wrong |
|---|---|---|
| tight, bgrx8888 | 0 | 25 |
| tight, rgb565 | **4146** | **353** |
| tight + JPEG level 9, bgrx8888 | **274** | **178** |

Two of the three overlap: no threshold accepts every correct frame and rejects
every wrong one. rgb565 works today only because `_expectMatch` falls through
to `_quantizedMatch`, which is a different comparison the documentation does
not mention. The documented metric serves the exact-match case alone.

## The comparison

Per pixel, the perceived colour difference in YIQ, from pixelmatch (Kotsarenko
& Ramos 2010):

    dY, dI, dQ  from the usual RGB -> YIQ matrix
    delta = 0.5053*dY^2 + 0.299*dI^2 + 0.1957*dQ^2

normalised by 35215, the largest delta two 8-bit pixels can produce, and scaled
to 0..255 so the number a script writes is on the same scale as a channel
value. Luma carries most of the weight, which is where a lossy encoder spends
least of its error budget and where the eye resolves most detail.

The screen matches when **every** pixel is within the fuzz. Not a mean, not
a count: a mean cannot see a small change (a 16x16 patch moves the mean
absolute error by 0.73 while JPEG alone moves it by 1.45), and a count needs a
second threshold that absorbs the change along with the noise.

**Optionally low-pass first.** Both images through a box blur of radius R before
differencing. This is the only thing measured that survives a genuinely lossy
transport, and it is what os-autoinst does for the same reason (grayscale, then
a 3x3 Gaussian, in `ppmclibs/tinycv_impl.cc`).

Pillow computes all of it -- `ImageMath` over F-mode bands for the YIQ delta,
`ImageFilter.BoxBlur` for the low pass. No new dependency.

## What it costs

Per comparison, and `expect` runs one per framebuffer update:

| | 256x192 | 1920x1080 |
|---|---|---|
| histogram RMS (today) | 0.09 ms | 3.2 ms |
| YIQ delta | 1.28 ms | 49.7 ms |
| YIQ delta, blurred | ~1.8 ms | ~68 ms |

50 ms per poll at 1080p is the cost of the float path. A per-channel RGB
maximum is 2.4 ms and, when it passes, the YIQ delta cannot fail -- so the
exact-match case, which is most of them, never enters the float path.

## Measurements

Worst accepted (a settled frame against its own scene) against best rejected (a
settled frame against the seven other scenes, plus every partially-drawn frame
against the scene it was still drawing). Partial frames come from feeding each
step's bytes in 4 KB chunks and sampling the framebuffer between them; they are
the "do not unblock on a half-painted screen" case. Every candidate rejected
all of them, so blocking behaviour does not discriminate between metrics --
lossy tolerance does.

Captures are real wire bytes from tigervnc, `--jpeg-quality` as noted:

| capture | histogram RMS | YIQ | YIQ + blur 2 |
|---|---|---|---|
| tight bgrx8888 | 0 / 25 | 0 / 127 | 0 / 87 |
| tight rgb565 | 4146 / 353 ✗ | 3 / 127 | 2 / 86 |
| tight JPEG level 9 | 274 / 178 ✗ | 2 / 127 | 1 / 87 |
| tight JPEG level 5 | 706 / 239 ✗ | **123 / 127** | 14 / 87 |
| tight JPEG level 0 | 1498 / 300 ✗ | **176 / 127** ✗ | 46 / 87 |

Unblurred YIQ is unusable below level 9: level 5 leaves a 3% margin and level 0
inverts. tigervnc drops to chroma subsampling at the lower levels, and chroma
error reaches 164 on saturated content -- more than YIQ's 3.5x chroma discount
absorbs. **Blur is not optional for a lossy transport.**

Blurred, one fuzz of 64 accepts every capture in the table (worst 46) and
rejects every wrong scene (best 86). Sensitivity survives it: a 2x2 pixel change
on a smooth screen reads 20 against a noise floor of 7.

## The surface

`expect` and `rexpect` keep their names and their arguments. Two options tune
them, alongside `--jpeg-quality` and the rest:

    --expect-fuzz N   per-pixel bound, 0..255 [derived from the format]
    --expect-blur R   box blur radius applied to both images [0]

**Fuzz, not tolerance.** `fuzz` is already the word in vncdo's own help text
(`expect FILE FUZZ`) and ImageMagick's for the same quantity, a per-pixel
colour-distance allowance. `tolerance` is spoken for in this repository: it is
the RGB quantization triple in `pixelformat.channel_tolerance` and in a
fixture's `conditions.json`, a different number on a different scale, and
overloading it would leave `tolerance_kind` ambiguous.

The default fuzz is computed from the negotiated pixel format, not chosen: a
format whose channel tolerance is (7, 3, 7) admits a worst-case YIQ delta of
7.7, so rgb565 defaults to 8 and an 8-bit-per-channel format to 0. This is the
`_quantizedMatch` rule, promoted from a hidden fallback to the documented
default.

`expect FILE FUZZ` keeps its optional third token, meaning that same bound and
**overriding `--expect-fuzz` for that one command**. The option sets a run's
default; the token tunes one wait. One script can wait on a smooth login dialog
and then on a desktop playing video, which the option alone cannot express.

`expect somescreen.png 0` -- the spelling in `docs/usage.rst` and in every
script that copied it -- goes on meaning "exact". A script passing a large RMS
number gets a lax match rather than the tight one it asked for; the number is
on a different scale now. That is a breaking change, taken deliberately while
the version is `2.0.0.dev0`, and it needs a CHANGELOG entry saying so.

The Python API takes the same two as keyword arguments:

    expectScreen(filename, fuzz=None, blur=0)
    expectRegion(filename, x, y, fuzz=None, blur=0)

`maxrms` becomes `fuzz`. It is a public keyword and the rename is a breaking
change for API callers, taken outright with no deprecated alias: the argument
it named no longer exists, and accepting a root-mean-square number under any
spelling would mean keeping the comparison this design removes.

## What this retires

`tests/goldens/capture.py` passes `--expect-fuzz 64 --expect-blur 2` when
`--jpeg-quality` is set, and drives `scene.vdo` for every capture.
`scene-lossy.vdo` is deleted, along with its `pause 1.5` pacing and the
throwaway `capture step.png` calls that existed only because `expect` could not
be trusted. `decoder-goldens.md` loses the "Sequencing a lossy capture"
section.

The committed fixtures are recorded wire bytes and do not change. Proving the
new path works means re-capturing against the fleet, which `make goldens`
already does.

## The level-5 fixture

A `tigervnc-tight-jpeg5-bgrx8888` fixture lands with this change, as its proof.
Level 9 is the one quality tigervnc encodes without chroma subsampling, so a
fixture captured there exercises none of what makes a lossy encoding hard --
every claim in Measurements about why the old comparison fails, and about why
blur is not optional, rests on bytes no committed fixture holds.

It could not land first. Captured against the old comparison, it failed the
suite on its fourth step:

    FAIL: test_decodes_to_its_oracle
      (test_goldens.TestGolden_tigervnc_tight_jpeg5_bgrx8888)
    tigervnc-tight-jpeg5-bgrx8888 step-03-d.bin.gz:
      pixel (17,16) decoded (198, 202, 53), expected (200, 200, 40)

That is the point of it. A fixture records how far its frames may sit from the
oracle, and `conditions.json` states that as an RGB triple -- `[8, 8, 8]` for
the level-9 capture -- which level-5 bytes miss by a wide margin: 229 against a
bound of 8. So `test_goldens.py` moves onto this comparison with the client,
and a `jpeg-lossy` fixture records `{fuzz, blur}` in place of the triple. The
`format-quantization` kind keeps the triple; it is the format's own number and
nothing about it changed. Under blurred YIQ the same fixture reads 14 against a
nearest wrong scene of 87.

Two independent captures of level 5, taken minutes apart from the same fleet,
produced identical separation figures across every candidate metric -- the
encoder is deterministic enough that a re-capture is a re-derivation, not a new
experiment.

Step labelling needs nothing. Both a level-5 and a level-0 capture distilled
eight labelled steps with no missing keysym patch, so the 48x48 flat patch
survives the encoder even at the worst quality tigervnc offers.

## Alternatives

**Smallest change that satisfies the request.** Make `_quantizedMatch`'s bound
caller-supplied and leave everything else alone: per-channel RGB maximum, one
number. It works for the committed level-9 fixture (worst correct 4, nearest
wrong 180) and fails on real level-5 bytes (229 against 180), where the design
is meant to be heading. Rejected for that.

**Per-pixel threshold plus a count allowance**, as Playwright and pixelmatch do
(`threshold` with `maxDiffPixels`), and as ImageMagick does (`-fuzz` with the
`AE` metric, the only fuzz-affected one). The per-pixel half is what this design
takes, name included; what it rejects is the count allowance on top. That
survives every encoding measured,
and it goes blind on noisy content: the count that absorbs the compression
noise absorbs a small change with it. It suits whole-page screenshots over a
lossless transport, which is not this.

**A perceptual hash** (dhash, ImageMagick's `PHASH`). Cheap and robust to
compression, blind to changes below roughly 32x32 pixels, and it already
overlaps on the rgb565 fixture -- 5 for a correct frame against 3 for a wrong
one.

**Template matching against a region**, as os-autoinst and SikuliX both do:
match a needle somewhere in a search window rather than the whole screen. That
is `rexpect`'s job and this design leaves it alone, but the prior art is a
reminder that whole-screen matching is the unusual choice, and that a
whole-screen aggregate is where sensitivity goes to die.

## Phasing

Five commits. Each leaves `make test` green and `flake8 --count --statistics
vncdotool tests` clean, with one stated exception in phase 4. `make typecheck`
is advisory in CI and run at the end.

**1. The comparison, wired to nothing.** A new `vncdotool/imagematch.py`: pure
Pillow, no Twisted, so the client and the golden suite can share one comparison
and neither has to reach into the other.

    fuzz_for_format(pixel_format) -> int    the (7,3,7) -> 7.7 computation
    worst_delta(a, b, blur=0) -> int        the largest YIQ delta, 0..255
    matches(a, b, fuzz, blur=0) -> bool     with the RGB fast path

`tests/unit/test_imagematch.py` drives it on synthetic images: identical frames,
one channel off, a luma change against a chroma change of the same magnitude,
what a blur radius does to a small patch, and the fast path agreeing with the
float path. The per-format default is a set -- every entry in `PIXEL_FORMATS` --
so it generates one case per format through `load_tests` rather than looping.

**2. The client uses it, RMS goes.** `_expectFramebuffer` stops building
`self.expected` from `image.histogram()` and keeps only `expected_image`.
`_expectMatch` becomes a call into `imagematch.matches`. `_quantizedMatch` is
deleted -- its rule is now the default fuzz rather than a fallback nobody
documented. `expectScreen(filename, fuzz=None, blur=0)` and
`expectRegion(filename, x, y, fuzz=None, blur=0)`; `maxrms` is gone from both.
The client carries `expect_fuzz` and `expect_blur` set from the factory, the way
`requested_jpeg_quality` already is.

Six tests in `tests/unit/test_client.py` assert on `cli.expected` as a
histogram and are rewritten against the new comparison. `CHANGELOG.rst` gets the
entry for the breaking change, under `(UNRELEASED)`.

**3. The CLI surface.** `--expect-fuzz` and `--expect-blur` parsed and
validated (fuzz 0..255, blur non-negative), onto the factory. `expect` and
`rexpect` take their trailing number only when the next token parses as one,
which incidentally fixes a live bug: `docs/usage.rst` documents `expect
password_prompt.png` with no number, and today that spelling dies on an
unhandled `IndexError` from `float(args.pop(0))`. Help text at
`command.py:161` and `:172`, the `docs/usage.rst` prose, and cases in
`tests/unit/test_command.py`.

**4. The goldens.** `conditions.json` grows a shape per tolerance kind: a
`jpeg-lossy` fixture records `{"fuzz": N, "blur": R}`, a `format-quantization`
fixture keeps its RGB triple, which is the format's own number and unchanged.
`test_goldens.py` compares through `imagematch` for the lossy kind.

`capture.py` stops using one number for two jobs. `JPEG_TOLERANCE` currently
serves both the keysym-patch read in `distill.split` and the fixture's recorded
bound; the patch read keeps its RGB triple, proven to work at level 0, and the
recorded bound becomes the fuzz pair. It passes `--expect-fuzz 64 --expect-blur
2` when `--jpeg-quality` is set and drives `scene.vdo` for every capture.
`scene-lossy.vdo` is deleted. `servers.mk` gains the level-5 line.

The `0` after each filename in `scene.vdo` goes too, and has to: a token beats
the option by design, so the script kept demanding an exact match and timed the
level-5 capture out at exit 40. Without it a lossless capture still gets
exactness from its pixel format, and an rgb565 capture still gets the step its
5-bit red cannot express.

The existing level-9 fixture's `conditions.json` is migrated in place. Its
bytes are not re-captured: they are 264K of binary that a re-capture would churn
for no gain, and nothing about them changed.

This is the phase that carries `tigervnc-tight-jpeg5-bgrx8888`, already captured
and sitting untracked. It stays untracked until this commit, because a fixture
recording `[8, 8, 8]` fails the suite as long as the old comparison is the one
reading it.

**5. The documents.** `decoder-goldens.md` loses "Sequencing a lossy capture"
and points here instead; its matrix gains the level-5 row. This spec's status
line changes. Then `make typecheck`, and `make testall` against the fleet to
confirm nothing in the functional suite leaned on the old behaviour.

## Not in scope

**`waitidle`** -- block until the framebuffer stops changing, no reference image
-- is a separate change and a separate spec. It is what `scene-lossy.vdo`'s
`pause` is really approximating, and it is what an agent driving vncdo through
`capture` wants. It would let the golden scripts drop `expect` altogether,
which is an argument for doing it, not for doing it here.
