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

### 1. ~~The app is not accessible.~~ Done — the app speaks for itself.

Sightline now voices its own interface. Every control confirms itself aloud, it
announces itself on startup, and Menu reads out the controls.

It deliberately does **not** route this through the platform screen reader.
VoiceView cannot be enabled on the virtual device at all (FL-011) and may be off
on real hardware, and an accessibility app that only works when another
accessibility feature is already switched on is not much use. Phrases are
pre-rendered PCM shipped with the bundle, so a confirmation never waits on the
network or a speech engine. React Native accessibility props are set as well,
for anyone who does have VoiceView running — untestable here, but harmless.

Two details that matter more than they look:

- **Interface speech interrupts description.** The user just pressed a button;
  telling them it took precedence over finishing a sentence about the film.
- **Startup speaks before playback starts, not over it.** The full controls list
  runs nearly thirteen seconds, so startup says a short line pointing at Menu
  and the long version is on demand. Talking across the opening of the film is
  the exact mistake this app exists to prevent.

**Still untested:** whether VoiceView works with it on physical hardware.

### 2. ~~No LICENSE and no README.~~ Done.

MIT licence, a README arranged so a judge can verify claims without running
anything, a mermaid architecture diagram, and the app finally has a name and an
icon rather than "Basic UI React Native Application for project sightline".

### 3. ~~"Real time" needs to be either true or reworded.~~ Made visible.

The app now detects that a video has no description, offers to create one, and
speaks its way through the work: listening for dialogue, watching what changes,
ranking, preparing the voice. Then it plays.

Generation went from **103 seconds to 29** on a 52-second trailer. Two changes
did it: describing segments concurrently, and asking for slightly fewer words
than the budget strictly allows — every overshoot cost a rewrite *and* a
re-synthesis, which is where the time actually was. The margin also stopped a
line being dropped for want of a retry, so it was faster and better.

Description is still generated before playback rather than during it. That is
the design — generate once for content nobody will ever describe by hand — but
the work is no longer invisible.

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
