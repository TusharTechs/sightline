# Status — 23 October 2026

Submission day.

## Done, and verified on device

| | evidence |
|---|---|
| Generated description | change gate 9/9 with 0 false positives; salience precision and recall 1.00 on the fixture |
| Video playback on Fire TV | MSE; URL mode is broken on this platform and avoided deliberately |
| Description audio on Fire TV | PCM on a `USAGE_ACCESSIBILITY` stream; ducks the film automatically |
| Fit-the-gaps and pause-and-explain | both modes, measured at 1x / 1.5x / 2x |
| Speech-based gap detection | 16x more usable time than silence detection on real footage |
| Ranked scheduling | rank fixed once; speed changes depth, never order |
| Co-viewing | room hears the film untouched, description goes only to the phone |
| Interactive questions | answers from the frame the television is actually on, and live on the hosted demo via AWS Lambda + API Gateway |

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

### 4. No blind user has operated the television app.

Two blind reviewers have shaped the design through correspondence, and they
have tested the web player and listened to the rendered clips. Seven faults
came out of their review in total, all fixed:

- A description arrived 0.15s after a line of dialogue ended, so the line
  itself was missed. The pause after speech is now 0.7s.
  See `pipeline/src/detect_speech.py`.
- Description stopped just after two minutes of a three-minute clip. The cause
  was `gaps[:max_cues]` truncating the film rather than capping the number of
  descriptions. A cap now applies after ranking, so what survives is the most
  needed description from anywhere in the film.
  See `pipeline/src/film_cues.py`.
- A high shot through rafters was described as "someone watches her sleep",
  inventing a character not in the film. Camera language is now rejected by
  `pipeline/src/preflight.py`.
- Attenuating a file by 3 dB flipped five onset classifications because the
  audio loader was reading 16-bit and clipping peaks. Fixed and guarded by
  `pipeline/src/stability.py`.
- On iOS, `film.volume` is read-only, so ducking did nothing and the score
  drowned out the description. The film now routes through a Web Audio gain
  node (`companion/phone.html`).
- VoiceOver repeated status lines continuously and played an empty-element tone
  whenever the transcript prepended a line. The live region now mutates only on
  state changes and the log is append-only (`companion/phone.html`).
- Once playback started on the web player, there was no way to stop except
  closing the tab, and pausing the video left an in-progress description
  speaking. The primary button now toggles **Pause / Resume** — halting the
  voice pool as well as the film — and **Escape** stops playback from anywhere.

What is still untested: nobody blind has operated the Fire TV app on a
television.

### 5. Smaller, real

- **The drop tone has never fired on the trailer.** At 1x every cue fits; the
  tone is exercised at 1.5x / 2x and in unit tests (`app/test/Scheduler.spec.ts`).
- **Questions take about 7 seconds.** Tolerable, not good.
- **Pause-and-explain has only been run on the walkthrough**, not on film.
- **Never run on physical hardware.** Not required for the hackathon, but
  required before Appstore submission, and it is where audio focus and ducking
  would be properly exercised.

## Open upstream

- Amazon's answer on the Vega Virtual Device URL-mode media bug
  ([topic 29117](https://community.amazondeveloper.com/t/audioplayer-url-mode-fails-with-media-err-src-not-supported-on-vvd-app-never-connects-to-com-amazon-media-server-both-official-media-samples-also-fail/29117)).
- Account-level `Error 002` on Amazon Bedrock, documented in
  [`FEEDBACK.md`](FEEDBACK.md).
