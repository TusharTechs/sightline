# Feedback for the Amazon Devices and AWS teams

Everything we found while building Sightline on Vega OS, written for the people
who can fix it rather than for a scoreboard.

Three documents sit behind this one:

- [`FRICTION-LOG.md`](FRICTION-LOG.md) has the fifteen findings in full, each
  with the task attempted, the steps taken, expected against actual, a severity,
  the workaround used, and a suggestion. Written while building rather than
  remembered afterwards.
- [`VEGA-FIELD-NOTES.md`](VEGA-FIELD-NOTES.md) is what we learned about the
  platform that is not a fault, just knowledge we wish we had started with.
- [`docs/where-it-works.md`](docs/where-it-works.md) is where our own product
  stops working, measured.

The pattern across nearly all of it: **the failures were silent.** No track
lists, no button events, every toggle undoing itself, a manifest requirement
ignored, a media API doing nothing at all. In each case the developer's first
assumption is that the fault is theirs, and the time lost is spent looking in
the wrong place. A warning in the console would have been worth more than any
documentation page.

---

## Part 1: feature requests

Sixteen requests, grouped by area and each with a priority. Every one came out
of something that actually cost us time on this build, and the full reproduction
for each is in the friction log entry named beside it.

### A. AWS services

**A1. Bedrock: an error that names the missing agreement.
Priority: Critical.**
`Error 002: Access to Bedrock models is not allowed for this account` gives a
developer nothing to act on. It was returned in every region, for every model,
with bare model IDs and both inference profile forms, while S3, Polly and
Transcribe worked on the same credentials in the same session. The real cause,
`agreementAvailability: NOT_AVAILABLE`, is visible only from
`get-foundation-model-availability`, which you have to already know exists. The
per model toggle in the console does not clear it.
*Why it matters to us:* Bedrock was the planned model backend. The client is
written and shipped in the repository and has never run. We shipped against a
direct model API instead, which is a worse outcome for Amazon than for us.
*Ask:* name the missing agreement in the error, or surface agreement status
beside the model in the console.

**A2. Transcribe: a direct upload path for short files.
Priority: Important.**
Transcribe takes input from an S3 bucket rather than a direct upload, so every
job means writing an object and cleaning it up.
*Why it matters to us:* for a 52 second clip the S3 round trip is most of the
wall clock time of that stage, and our users are waiting on it. It also closed
off a feature: spoken questions on iPhones need server side transcription, and
the batch path is far slower than anyone waits for an answer about the shot
they are looking at.
*Ask:* a direct upload path for small files, or streaming transcription
documented as the interactive option alongside the batch one.

**A3. Polly: an option to return audio without padding.
Priority: Important.**
Polly pads both ends of its output with silence.
*Why it matters to us:* every description is fitted into a measured gap between
lines of dialogue, and that padding is charged against the gap budget. It had
to be detected and trimmed before anything could be measured.
*Ask:* a flag to return unpadded audio, or document the padding so people know
to trim it.

**A4. Polly: document the delivered speaking rate per voice and engine.
Priority: Important.**
The effective rate is not the rate you request. We asked for 170 wpm and every
single line overflowed its gap. Measured after trimming the padding, the real
figure was 203 wpm, a 19 percent difference.
*Why it matters to us:* our whole timing model is built on predicting how long
a line will take before we synthesise it. We lost a day to this and only found
it by measuring.
*Ask:* publish typical rates per voice and engine, or return the expected
duration with the synthesis response.

### B. Vega platform capability

**B1. Per stream audio output routing.
Priority: Important. This is the one we would most like built.**
`keplerscript-audio-lib` is genuinely good: `AudioPlaybackStreamBuilder` with
`AudioUsageType.USAGE_ACCESSIBILITY` gives a concurrent stream that ducks media
automatically. What is missing is any way to route an individual stream to a
specific output device. The documentation covers whole device switching between
HDMI and a Bluetooth headset, but a stream cannot go to one output while media
continues to another.
*Why it matters to us:* this is the defining problem in home audio description.
Description is a single room wide track, so a household either imposes it on
everyone present or the blind viewer goes without. Cinemas solved this two
decades ago with personal receivers and it remains unsolved in the living room.
We worked around it by sending description to a phone over the local network,
which works but should not have to exist.
*Ask:* allow an output device target on `AudioPlaybackStreamBuilder`, so a
`USAGE_ACCESSIBILITY` stream can go to a connected Bluetooth device while media
continues on HDMI. Bluetooth LE Audio and Auracast make multi endpoint routing
increasingly standard and Fire TV is well placed for it. One capability would
let a single screen serve viewers with different access needs at the same time,
which is currently impossible on any television platform. See FL-005.

**B2. Track enumeration in URL mode, or a note saying it is absent.
Priority: Important.**
`video.audioTracks` and `video.textTracks` never populate in URL mode. The
native GStreamer pipeline detects the tracks correctly; the metadata is not
bridged to the JS side. Confirmed by Amazon in the developer community as a
known limitation.
*Why it matters to us:* enumerating and switching audio tracks was the original
architecture for delivering an alternate description rendition. We designed
against the documented W3C interface, got empty lists with no error, and lost
time before finding the community thread.
*Ask:* bridge the metadata, or state the limitation in the URL mode section of
the W3C Media API page. The page presents URL mode and MSE mode as a
convenience tradeoff without mentioning that enumeration is absent from one of
them. See FL-001.

**B3. App level speech to text.
Priority: Nice-to-have.**
There is no app level speech recognition, and the documentation reads as
contradictory on the point.
*Why it matters to us:* asking a question aloud is the natural interaction for
a viewer who cannot see the screen, and it is the one part of our multi modal
story we had to route around.
*Ask:* an app level recognition API, or an explicit "no app level speech
recognition" statement in the docs so nobody designs around it. See FL-004.

### C. Vega tooling, CLI and the virtual device

**C1. Media playback on the Vega Virtual Device.
Priority: Critical.**
Both official media samples fail on the current OS 1.2 `vvrp-tv-arm64` image
with SDK 0.24.9914, in different ways. Separately, `canPlayType()` returns
`"probably"` for a type the player then refuses, which is a bug in its own
right: that API exists precisely to avoid this situation.
*Why it matters to us:* we are building a media application, and the simulator
is the only target most entrants have. This is the difference between choosing
the simulator and buying hardware, and the documentation currently presents the
VVD as a general purpose development target.
*Ask:* verify media playback on the current image using the two official
samples as regression tests, and if it requires physical hardware, say so
prominently in the VVD documentation. See FL-012.

**C2. VoiceView on the virtual device.
Priority: Critical for accessibility work.**
The documented shell method for enabling VoiceView on the VVD fails with a
permission error. The developer shell does not have the privileges the
documented instruction requires.
*Why it matters to us:* we are building an accessibility product and could not
enable the platform screen reader on the only device we had. It is the reason
our app speaks every control itself rather than relying on VoiceView, which is
a design decision forced by tooling rather than chosen.
*Ask:* grant the developer mode shell permission to write accessibility config,
since it is a developer device by definition, or add
`vega device set-accessibility voiceview on|off`. Failing either, correct the
FAQ to say the shell method cannot work on the VVD. See FL-011.

**C3. Native crash symbolication for external developers.
Priority: High.**
Symbolicating a native crash requires Amazon internal authentication, so an
external developer with a SIGSEGV has an unreadable stack and nowhere to go.
*Why it matters to us:* a reference sample crashed on the virtual device and we
could not read the crash to find out why.
*Ask:* a public symbol server for release builds, or symbols shipped with the
SDK. See FL-009.

**C4. `vega device run-cmd` runs sandboxed, and does not say so.
Priority: Important.**
Platform diagnostics run through `run-cmd` return results from inside a sandbox,
which are silently misleading rather than wrong in any visible way.
*Why it matters to us:* we used it to check platform state while debugging and
believed answers that were not true of the device.
*Ask:* state the sandboxing in the command help and documentation, or provide an
unsandboxed diagnostic mode. See FL-013.

**C5. Enforce `[needs.service]` in the manifest.
Priority: Important.**
A manifest that requires a service which does not exist installs and runs
anyway. The requirement is not enforced.
*Why it matters to us:* a typo in a service name is silent, and the failure
surfaces later as a missing capability at runtime with nothing pointing at the
manifest.
*Ask:* enforce `[needs]` for services the way the equivalent is enforced
elsewhere, or warn at install time. See FL-014.

**C6. Missing media services in `manifest.toml` fail silently.
Priority: Important.**
If the manifest is missing the media services, media APIs simply do nothing. No
error, no warning.
*Why it matters to us:* our first player did nothing at all and looked like our
own bug for some time.
*Ask:* emit a runtime warning when a media API is called and the required
service is not declared. See FL-002.

**C7. `vega project generate` ignores the project name and exits 1 on success.
Priority: Nice-to-have.**
It generates into the wrong place and reports failure on a successful run.
*Why it matters to us:* small, but it is the first command a new developer runs,
and a non zero exit on success teaches people to ignore exit codes.
*Ask:* create `<outputDir>/<name>/` and exit 0 on success. See FL-010.

### D. Documentation and type definitions

**D1. `TVTypes.d.ts` disagrees with the runtime.
Priority: Critical.**
The runtime field is `eventKeyAction`; the SDK's own type definition documents
it as `eventAction`. Filtering on the documented name matches nothing, so every
press fires twice and every toggle instantly undoes itself.
*Why it matters to us:* every control in the app is a remote button, and each
one silently undid itself. A type definition that disagrees with the runtime is
worse than no type definition, because it is the thing developers trust most.
*Ask:* correct the type definition, or emit both fields. See FL-015.

**D2. Say that `useTVEventHandler` comes from react-native-kepler, and that
React Native's own `TVEventHandler` does not work.
Priority: Critical.**
React Native's `TVEventHandler` exists on the platform, registers nothing, and
fails silently.
*Why it matters to us:* we imported it, no button did anything at all, and
there was no error to chase. Every React Native TV tutorial shows the React
Native one, so every porting developer will reach for it first.
*Ask:* state it in the Vega app documentation, and emit a deprecation warning or
anything at all in the console. See FL-015.

**D3. State which `eventType` the select button produces.
Priority: Important.**
Both `enter` and `select` are listed in the union without saying which actually
arrives.
*Why it matters to us:* we guessed, guessed wrong, and it failed silently. We
now handle both.
*Ask:* say which one a remote produces. See FL-015.

### E. Reference samples

**E1. The recommended starter sample conflicts with platform media guidance.
Priority: Important.**
The multi TV sample's cross platform goal leads it away from what the platform
documentation recommends for media.
*Why it matters to us:* it is the sample a new developer is pointed at first,
and following it leads away from the documented path. See FL-003.

**E2. `vega-video-sample` declares AudioTracks support but implements none.
Priority: Important.**
*Why it matters to us:* we went to the sample specifically to see how track
selection was meant to work, which is exactly what a sample is for.
*Ask:* add an audio track selector to the sample, or stop declaring the support.
See FL-006.

**E3. The sample's `app:launch` script does not work with the current CLI.
Priority: Nice-to-have.**
*Ask:* update `app:launch` in the sample's `package.json`. See FL-007.

**E4. A reference sample crashes with SIGSEGV on the virtual device, with two
RCT-folly versions loaded.
Priority: High.**
*Why it matters to us:* combined with C3, an unreadable crash in Amazon's own
sample is a dead end for an external developer. See FL-008.

### If the team only reads three

**A1 (Bedrock error), C1 (media on the virtual device) and D1 with D2 (remote
input).** Those three cost us the most time, and all three are the kind of
failure where nothing is reported and the developer assumes the fault is
theirs. B1, per stream audio routing, is the one we would most like to see
built, but it is a feature rather than a fix.

---

## Part 2: what we used, what worked, what did not

**Vega SDK 0.24.9914 and Vega CLI 1.3.4.** Building, packaging, installing and
launching the app, and running the virtual device.

**React Native for Vega (`@amazon-devices/react-native-kepler` ~4.0.0, RN
0.83).** The whole application layer: the player surface, the heads up display,
captions and remote handling.

**`@amazon-devices/react-native-w3cmedia` 2.3.2.** Video playback on the
device, in MSE mode with Shaka Player.

**`@amazon-devices/keplerscript-audio-lib` 2.0.18.** A second audio stream for
description, separate from the film, so description can duck the film rather
than fight it.

**Vega Virtual Device.** Every take in the demo video was recorded on it.

**Amazon Devices Builder Tools (MCP).** Documentation search during the build.

**Amazon Transcribe, Amazon Polly, Amazon S3, AWS Lambda, Amazon API Gateway,
Amazon Bedrock.** As described in the AWS Builder answer above.

### What worked well

**Transcribe.** Word level timestamps are exactly the right primitive, and
accuracy on film dialogue over a musical score was excellent. It changed the
product rather than merely serving it.

**Polly generative.** The voice quality is genuinely good, and PCM output means
no decoding on the device.

**S3.** Unremarkable in the best possible way. No surprises at any point.

**`keplerscript-audio-lib`.** A separate playback stream was the right model for
this problem, and ducking worked exactly as we hoped.

**Vega Virtual Device.** Stable enough to record a three minute demo on, and
fast to restart.

**Amazon Devices Builder Tools (MCP).** `search_documentation` and
`read_document` were genuinely useful, and several answers we needed were only
findable through them.

### What needs work

**Bedrock.** Refused at the account level with an error that names no cause.
Detail in the AWS Builder answer and in the feature requests above. This is the
single item we would most like fixed.

**W3C Media in URL mode.** `audioTracks` and `textTracks` never populate, and
the documentation does not say so. FL-001.

**`TVEventHandler` from react-native.** It exists on the platform, registers
nothing, and fails silently, so no button did anything at all and there was no
error to chase. `useTVEventHandler` from react-native-kepler is the working
path. A deprecation warning, or anything at all in the console, would have
saved hours.

**`eventKeyAction` versus `eventAction`.** The runtime field is
`eventKeyAction`; the SDK's own `TVTypes.d.ts` documents it as `eventAction`.
Filtering on the documented name matches nothing, so every press fires twice
and every toggle instantly undoes itself.

**Polly padding and speaking rate.** Undocumented, and invisible until every
timed line overflows.

**Transcribe requiring S3 for short files.** Most of the wall clock of that
stage for a one minute clip.

### Onboarding, zero to hello world

**Vega: good.** `vega project create`, build, and launch on the virtual device
worked the first time and the getting started path is clear. Reaching a running
app was comfortably same day.

**The gap is between hello world and the second thing.** Everything above in
question 3 was discovered after the tutorial ended, and each one presented as
silence rather than as an error: no track lists, no button events, every toggle
undoing itself. Time was lost to things that looked like our own bugs.

**AWS: straightforward,** except Bedrock, where onboarding never completed at
all because the account was refused and the error did not say why.

**Documentation search via MCP was the thing that unblocked us most often.**

### Would we build with these again

**Yes,** with one exception.

**Vega and Fire TV: yes.** The platform is a good fit for this problem, and a
television is the right place for audio description to live. A second audio
stream alongside the film is exactly what this needed, and that is a device
capability rather than something we worked around. The friction we hit was
mostly documentation and silent failure, which is fixable, rather than missing
capability.

**Transcribe: yes,** emphatically. It changed what the product could be.

**Polly: yes.** Measure the rate yourself first.

**S3, Lambda, API Gateway: yes.** No complaints.

**Bedrock: we would like to, and we could not.** The client is written and
waiting. If the account level refusal is resolved, we would move to it.

---
