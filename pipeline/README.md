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
| 4. Speech + word budget | `src/speech.py` | no | works — Amazon Polly (generative), `say` fallback |
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

## Model backend

Bedrock, via the Anthropic SDK's `AnthropicBedrockMantle` client, on
`anthropic.claude-opus-5` with adaptive thinking and structured outputs. The
verdict is a typed object rather than parsed prose, so "the model replied in a
shape we could not read" can never be scored as a salience decision.

```bash
tools/make-ca-bundle.sh                       # once
export SIGHTLINE_CA_BUNDLE=~/.config/sightline-ca.pem
export SIGHTLINE_AWS_PROFILE=sightline        # keep it off the default profile
tools/preflight.sh                            # checks TLS, credentials, model access
```

`tools/make-ca-bundle.sh` exists because this machine's network terminates TLS
with its own chain, which otherwise breaks both the AWS API
(`CERTIFICATE_VERIFY_FAILED`) and `pip`. Building a bundle from the machine's own
trust store fixes both. Harmless on a normal network.

Backends: `bedrock` (default), `bedrock-legacy` (bedrock-runtime InvokeModel —
try this if the Mantle endpoint rejects the request signature), `claude` (local
CLI; currently cannot refresh OAuth non-interactively).

Backends in priority order: `bedrock` -> `anthropic` (first-party Claude API,
needs `ANTHROPIC_API_KEY`) -> `bedrock-legacy` -> `claude` (local CLI, currently
cannot refresh OAuth non-interactively).

### Bedrock is blocked on this account — diagnosed, not guessed

```
Error 002: Access to Bedrock models is not allowed for this account
```

What was ruled out:

| Checked | Result |
|---|---|
| Wrong account | No — CLI authenticates as the same account shown in the console |
| Wrong region | No — identical in us-east-1, us-west-2, ap-south-1, eu-central-1 |
| Model-specific | No — Opus 5, Sonnet 5, Haiku 4.5 and Sonnet 4.5 all identical |
| Needs an inference profile | No — bare, `us.` and `global.` prefixes all identical |
| Organization SCP | No — the account is not a member of an organization |
| IAM permissions | No — that returns `AccessDeniedException`, not `ValidationException` |
| Other AWS services | **S3, Polly and Transcribe all work** — Bedrock alone is refused |

`get-foundation-model-availability` reports `authorizationStatus: AUTHORIZED`,
`entitlementAvailability: AVAILABLE`, `regionAvailability: AVAILABLE`, and
`agreementAvailability: NOT_AVAILABLE`.

So this is account state that only AWS can change — creating an IAM user cannot
fix it. Raise it with AWS Support (Bedrock model agreement unavailable despite
being authorized and entitled), and check the account has a valid payment
method. Meanwhile use the `anthropic` backend.

## Scoring caveat

The fixture's author cannot also be its judge. The model has no access to
`ground-truth.json`, so a score here measures whether the pipeline *implements*
the salience rule faithfully — not whether the rule generalises. That second
question is answered by real footage and by blind testers, not by this fixture.

## Speech and audio format

**Amazon Polly**, generative engine, falling back to neural where a voice or
region lacks it, and to macOS `say` with `SIGHTLINE_TTS=say`. Polly is the
default for three reasons: it is portable (`say` is macOS-only, and this project
has to build on another machine), the generative voices are better, and it
returns PCM natively. It also keeps an AWS service in the build while Bedrock is
blocked.

Output is **16-bit 48 kHz stereo interleaved PCM**, which is what
`AudioPlaybackStream.writeAsync()` takes on Vega. Never MP3 — all decoding
happens here, never on the device. See `HANDOFF.md` and `probes/`.

## Not built yet

- **Fit-the-gaps mode.** Needs silence detection on a real soundtrack. The word
  budget it depends on (`speech.budget_words`) is done and speed-aware.
- **Interactive questions** mid-playback.
- **Companion phone channel.**
