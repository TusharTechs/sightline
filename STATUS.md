# Status — 13 September 2026

Day 7 of 46. **39 effective days** (treat 22 October as the deadline).

## Done, and verified on device

| | evidence |
|---|---|
| Generated description | change gate 9/9 with 0 false positives; salience precision and recall 1.00 on the fixture |
| Video playback on Fire TV | MSE; URL mode is broken on this platform and avoided deliberately |
| Description audio on Fire TV | PCM on a `USAGE_ACCESSIBILITY` stream; ducks the film automatically |
| Fit-the-gaps and pause-and-explain | both modes, measured at 1x / 1.5x / 2x |
| Speech-based gap detection | 17x more usable time than silence detection on real footage |
| Ranked scheduling | rank fixed once; speed changes depth, never order |
| Co-viewing | room hears the film untouched, description goes only to the phone |
| Interactive questions | answers from the frame the television is actually on |

## Not done — in the order I would fix them

### 1. The app is not accessible. *(worst problem we have)*

There is no screen-reader support, no audio feedback, and no way to know which
mode you are in without reading the HUD. A blind person cannot currently operate
Sightline unaided.

That is a product failure before it is a judging problem, and a judge will find
it in thirty seconds. Everything else on this list is smaller.

### 2. No LICENSE and no README.

The Open Source mini-challenge is unwinnable without them, and this is an hour
of work. Nothing else has a better ratio.

### 3. "Real time" needs to be either true or reworded.

Description is generated **ahead of playback** and the app fetches a prebuilt
bundle. Questions are answered live; the description track is not. That is a
perfectly good design — generate once for content nobody will ever describe by
hand — but it is not what "real time" implies, and a judge reading the claim and
then seeing a prebuilt file has caught us in something.

Two honest routes: describe it accurately, or wire generation to the app so the
claim is visible. The second is stronger, because otherwise the generation — the
part with all the work in it — never appears on screen.

### 4. No blind user has actually used it.

the ADP list reviewer has shaped the design through correspondence and has the clips, but has
not played them yet. Nobody has operated the app or the phone. Every quality
claim rests on my judgement and one fixture I wrote myself.

Saksham Trust and Score Foundation have not replied.

### 5. Smaller, real

- **The drop tone has never fired.** No run has dropped a cue; the idea is built
  and untested.
- **Questions take about 7 seconds.** Tolerable, not good.
- **One hardcoded timeline.** No way to choose content in the app.
- **Pause-and-explain has never been run on film**, only on the walkthrough.
- **No error handling story.** Unclear what the app does if the service dies
  mid-playback.
- **Never run on physical hardware.** Not required for the hackathon, but
  required before Appstore submission, and it is where audio focus and ducking
  would be properly exercised.

## Then

- Devpost writeup.
- Demo video, on the finished product.
- Amazon's answer on the media bug, whenever it comes.
