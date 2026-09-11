# Sightline pipeline

Generates audio description for content that has none. Runs entirely off-device;
the Vega app is a thin client that receives PCM and timings.

## The idea it is built around

Three constraints, all from a blind accessibility professional on the ACB Audio
Description Project list, and all architectural rather than cosmetic:

1. **Describe the change, not the frame.** Describe the frame and you get "a
   settings window with a list of options" over and over while the box that just
   got ticked goes unmentioned. The information is in the difference between two
   moments.
2. **A change matters when it changes what you can do next.** Everything is a
   difference once you diff frames — pointers move, lists scroll. This is the
   filter. The same rule decides when to pause, at no extra cost.
3. **Playback speed is a first-class test condition.** Many listeners run at
   1.5–2x. Gap budgets are computed in playback time, and the answer to a
   shorter gap is *fewer words*, never faster speech.

## Stages

| Stage | File | Model needed | Status |
|---|---|---|---|
| 1. Change gate | `src/detect_changes.py` | no | **works — 9/9 on the fixture, 0 false positives** |
| 2+3. Salience + description | `src/salience.py` | **yes** | scaffolded; blocked on a model backend |
| 4. Speech + word budget | `src/speech.py` | no | works |
| 5. Evaluation | `src/evaluate.py` | no | works |
| 6. Render (pause mode) | `src/render_described.py` | no | works |

The gate is deliberately sensitive and dumb. Diff magnitude is a terrible
salience proxy — a scroll changes nearly every pixel and means nothing, a ticked
checkbox changes ~400 pixels and changes everything — so the gate only finds
*where and when* something moved, and the model decides whether it matters.

## The fixture

`fixtures/walkthrough/` is a synthetic settings walkthrough whose state is a
pure function of `?t=`, so frames are reproducible and the ground truth is
exact. It contains 9 changes: 5 that change what you can do (checkbox ticked,
control enabled, button enabled, modal opens, save completes) and 4 that do not
(focus ring moves, tooltip, focus moves again, list scrolls).

That mix is the point — it is designed so that a system which describes every
difference scores badly, and only one applying the salience rule scores well.

```bash
FPS=8 DUR=11.0 fixtures/walkthrough/render.sh    # ~5 min, regenerates frames + mp4
```

## Running it

```bash
python3 src/detect_changes.py fixtures/walkthrough/frames --fps 8 --out out/changes.json
python3 src/evaluate.py fixtures/walkthrough/ground-truth.json --changes out/changes.json

# stage 2+3 here, once a model backend works:
# python3 src/salience.py fixtures/walkthrough/frames out/changes.json --fps 8 --out out/judged.json
# python3 src/evaluate.py fixtures/walkthrough/ground-truth.json --judged out/judged.json

python3 src/render_described.py fixtures/walkthrough/walkthrough.mp4 \
    out/reference-descriptions.json --mode pause --out out/walkthrough-described.mp4
```

## Model backend — the open blocker

Neither path works from this machine yet:

- **Bedrock** (the intended path, and it feeds the AWS Builder mini-challenge):
  no credentials configured, and the AWS API is additionally unreachable because
  of local TLS interception (`CERTIFICATE_VERIFY_FAILED`). Needs credentials for
  the hackathon account plus an `AWS_CA_BUNDLE` that trusts the local chain.
- **`claude` CLI**: `Failed to authenticate: OAuth session expired and could not
  be refreshed` when invoked non-interactively.

Until one is fixed, stage 2+3 cannot be scored. Note also that the fixture's
author cannot be its judge — the salience score is only meaningful from a model
that has not seen `ground-truth.json`.

## Audio format

Speech is rendered to **16-bit 48 kHz stereo interleaved PCM**, which is what
`AudioPlaybackStream.writeAsync()` takes on Vega. Never MP3 — all decoding
happens here, never on the device. See `HANDOFF.md` and `probes/`.

## Not built yet

- **Fit-the-gaps mode.** Needs silence detection on a real soundtrack. The word
  budget it depends on (`speech.budget_words`) is done and speed-aware.
- **Interactive questions** mid-playback.
- **Companion phone channel.**
