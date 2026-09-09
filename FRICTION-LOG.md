# Sightline — Friction Log

Amazon Developer Hackathon 2026 · Fire TV / Vega OS track
Started: 8 September 2026

Format per entry: task attempted · steps taken · expected vs actual · severity ·
workaround · actionable suggestion.

---

## FL-001 — `audioTracks` / `textTracks` never populate in URL mode

**Severity:** High

**Task attempted.** Determine whether a Vega app can enumerate and switch between
multiple audio tracks at runtime — the core requirement for delivering an
alternate audio-description rendition.

**Steps taken.** Read the W3C Media API page (`/docs/vega/0.24/media-player`),
which documents `HTMLMediaElement` support and lists URL mode as the path for
flat MP4/MP3/MKV files. Searched the developer community for track enumeration.

**Expected.** Since Vega implements the W3C `HTMLMediaElement` interface,
`video.audioTracks` (AudioTrackList) should populate for a file containing
multiple audio tracks, in either playback mode.

**Actual.** In URL mode, `video.audioTracks` and `video.textTracks` never
populate. The native GStreamer pipeline detects the tracks correctly, but the
metadata is not bridged to the JS-side W3C properties. Confirmed by Amazon in
the developer community as "a known limitation": URL mode is designed for simple
non-adaptive playback. Embedded MKV subtitle tracks are also intentionally
unsupported in URL mode.

**Workaround.** Use MSE mode with Shaka Player, which provides full track
enumeration and selection. `addTextTrack()` covers external subtitles in URL
mode but does nothing for audio track selection.

**Actionable suggestion.** State this limitation directly on the W3C Media API
documentation page, in the URL mode section. The page presents URL mode and MSE
mode as a convenience/capability tradeoff without indicating that track
enumeration is absent from one of them. A developer who reads only the docs will
implement against URL mode, get silent empty track lists, and lose time before
finding the community thread. A one-line note plus a pointer to MSE mode would
prevent this entirely.

---

## FL-002 — Missing media services in manifest.toml fail silently

**Severity:** Medium

**Task attempted.** Understand the prerequisites for media playback in a Vega
app before writing any code.

**Steps taken.** Read the `amazon-devices-vega-media-player` skill shipped with
Amazon Devices Builder Tools.

**Expected.** A missing required service declaration would produce an error at
build, install, or playback time.

**Actual.** Per the skill's own "Common Mistakes" table: if media services are
not declared under `[wants]` in `manifest.toml`, the result is "no video output,
no errors." A silent failure with no diagnostic.

**Workaround.** Declare the required media services in `manifest.toml` up front.
For DRM, both `com.amazon.drm.key` and `com.amazon.drm.crypto` are required.

**Actionable suggestion.** Emit a runtime warning when a media API is called
without the corresponding service declared — even a console warning naming the
missing service would turn an unbounded debugging session into a ten-second fix.
Better still, validate at build time, since the manifest is available then.

---

## FL-003 — Recommended starter sample conflicts with platform media guidance

**Severity:** Medium

**Task attempted.** Choose a starter sample for a Fire TV media application.

**Steps taken.** Watched the official Devpost build session, in which
`AmazonAppDev/react-native-multi-tv-app-sample` was demonstrated and recommended
as the getting-started path. It is also listed first among Fire TV starter
samples on the hackathon resources page. Separately, read the
`amazon-devices-vega-media-player` skill.

**Expected.** The officially recommended starter would align with the platform's
documented media best practice.

**Actual.** `react-native-multi-tv-app-sample` implements playback with
`react-native-video`. The Vega media-player guidance lists "using ExoPlayer or
react-native-video" in its Common Mistakes table, directing developers to
`@amazon-devices/react-native-w3cmedia` instead. A developer following the
recommended starter for a media app is starting on the discouraged path.

**Workaround.** Use `AmazonAppDev/vega-video-sample` as the base for media
applications; it uses the W3C Media API directly.

**Actionable suggestion.** The multi-TV sample's cross-platform goal makes
`react-native-video` a reasonable choice for it, so the fix is guidance rather
than code: note on the resources page and in the build session which sample to
start from for media playback specifically, and why. As written, the
recommendation and the best practice point in opposite directions.

**Second observation, same theme.** The resources page lists eight starter
samples under a single "Fire TV" heading with no indication of which target Vega
OS and which target Fire OS. `hello-world-fire-tv-react-native`, described as "a
five-minute React Native Hello World for Fire TV", is actually an Expo /
`react-native-tvos` project with no `manifest.toml` and no Kepler runtime — it
cannot run on the Vega Virtual Device at all. Vega and Fire OS require entirely
different toolchains, so this is not a detail: a developer who picks that sample
intending to build for Vega has picked the wrong platform without being told.
Label each sample with its target OS in the list.

---

## FL-004 — No app-level speech-to-text; documentation reads as contradictory

**Severity:** Medium

**Task attempted.** Determine whether a Vega app can accept a spoken question
from the viewer — e.g. "who else is in this scene?" — during playback.

**Steps taken.** Searched the documentation and developer community for speech
recognition, microphone, and STT APIs.

**Expected.** Given VoiceView, the Accessibility API and an audio library with
input concepts, some app-controlled speech recognition path.

**Actual.** None exists. Amazon confirmed in the community that "VegaOS does not
expose an app-level speech-to-text API like Android's SpeechRecognizer for custom
speech recognition flows." The only supported path is the platform keyboard's
microphone on a focused `TextInput`, or press-and-hold on the Alexa button.
Notably, an Amazon respondent acknowledged that two earlier community threads
"read as contradictory" on this point — one referenced a "KeplerScript speech
API" that turns out to be the Accessibility API (speech *output*) and the Audio
Lib (routing and volume), neither of which does recognition.

**Workaround.** Move voice input off the television entirely — a companion
device supplies the microphone.

**Actionable suggestion.** Add an explicit "no app-level speech recognition"
statement to the Accessibility and Audio Lib documentation, naming the supported
alternatives. The absence is currently only discoverable by finding a community
thread that corrects two other community threads. A developer designing a
voice-driven feature will architect around a capability that does not exist.

---

## FL-005 — Feature request: per-stream audio output routing

**Severity:** Nice-to-have (feature request)

**Context.** `@amazon-devices/keplerscript-audio-lib` is genuinely good for this
use case. `AudioPlaybackStreamBuilder` plus `AudioUsageType.USAGE_ACCESSIBILITY`
gives a concurrent audio stream that ducks media automatically, and
`setDuckingPolicy` allows explicit control via `duckVolume`. Building
real-time audio description on Vega is well supported because of it.

**The gap.** There is no way to route an individual stream to a specific output
device. The documentation covers whole-device switching between HDMI and a
Bluetooth headset — the app detects the change and switches codec — but a stream
cannot be directed to one output while media continues to another.

**Why it matters.** This is the defining problem in home audio description.
Description is a single room-wide track, so a household either imposes it on
everyone or the blind viewer goes without. Cinemas solved this two decades ago
with personal receivers, and it remains unsolved in the living room. A
`USAGE_ACCESSIBILITY` stream is *precisely* the stream that should be routable
to a personal output — that is what the usage type is for.

**Actionable suggestion.** Allow an output-device target on
`AudioPlaybackStreamBuilder`, so a `USAGE_ACCESSIBILITY` stream can be sent to a
connected Bluetooth device while media continues on HDMI. Bluetooth LE Audio and
Auracast make multi-endpoint routing increasingly standard, and Fire TV is well
placed for it. This single capability would let one screen serve viewers with
different access needs simultaneously — currently impossible on any TV platform.

---

## FL-006 — Reference sample declares AudioTracks support but implements none

**Severity:** Medium

**Task attempted.** Find a worked example of runtime audio-track selection to
mirror, having established (FL-001) that MSE mode with Shaka is the only path
that supports it.

**Steps taken.** Cloned `AmazonAppDev/vega-video-sample`, the flagship media
reference app. Searched `src/` for `audioTracks`, `selectAudioLanguage`,
`getAudioLanguages` and related identifiers. Read the Shaka wrapper at
`src/w3cmedia/shakaplayer/ShakaPlayer.ts` and the media-controls types.

**Expected.** The sample declares audio-track support in its own manifest —
`features = ["AdvancedSeek", "VariableSpeed", "AudioTracks", "TextTracks"]`
under the Vega Media Controls interface — so some implementation should back it.

**Actual.** No audio-track handling exists anywhere in the sample. There is a
complete captions implementation (`types/Captions.ts`, caption menu, caption
selection), but the Shaka wrapper's only track-related call is
`setTextTrackVisibility(true)`. The manifest advertises a capability the sample
does not demonstrate.

**Impact.** Combined with FL-001, a developer implementing multi-audio-track
support has: no URL-mode support, no documentation of the MSE-mode approach on
the media player page, and no worked example in the reference app. The path is
discoverable only by reading Shaka Player's own upstream documentation and
inferring how it binds to Vega's `HTMLMediaElement`. Audio description is one of
the accessibility use cases this platform explicitly prioritises, and audio-track
selection is its foundation.

**Workaround.** Work directly against Shaka Player's track APIs and mirror the
structure of the existing caption menu, which is a good template.

**Actionable suggestion.** Add an audio-track selector to `vega-video-sample`
alongside the existing caption menu — the UI pattern is already there, so this is
a small addition with high leverage. Failing that, add a short audio-track
selection example to the W3C Media API documentation showing the Shaka call
sequence in MSE mode. Either would close the gap; right now the sample's manifest
promises something no code in the repository shows how to do.

---

## FL-007 — Sample's `app:launch` script is incompatible with current CLI

**Severity:** Medium

**Task attempted.** Build, install and launch `vega-video-sample` on the Vega
Virtual Device using the sample's documented one-command flow,
`npm run app:build:debug`.

**Steps taken.** Fresh install of Vega CLI 1.3.4 with SDK 0.24.9914 (both current
as of 8 September 2026). Cloned the sample, ran `npm install`, then
`npm run app:build:debug`.

**Expected.** The chained script — `build:debug`, then `app:install:debug`, then
`app:launch` — builds, installs and launches the app.

**Actual.** Build and install both succeed
(`Installing/Updating '/tmp/keplervideoapp_aarch64.vpkg' ...success`). The launch
step then fails:

```
> kepler device launch-app
Vega CLI argument error: Missing required argument(s).
Either --appName or --directory must be provided
```

The sample's `app:launch` script is `kepler device launch-app` with no arguments,
but CLI 1.3.4 requires one of `--appName` or `--directory`. The sample's other
scripts pass `--dir .`; this one does not.

**Workaround.** Run the launch manually:
`vega device launch-app --appName com.amazondeveloper.keplervideoapp.main`
(or `--dir .` from the project root). The app then launches correctly.

**Actionable suggestion.** Update `app:launch` in the sample's `package.json` to
`kepler device launch-app --dir .`, matching the sibling `app:install` scripts.
This is a one-word fix in the flagship media sample, and it currently breaks the
first thing a new developer runs — the last step of the getting-started flow,
after a ten-minute build has apparently succeeded. Worth also checking the other
Vega samples for the same stale invocation.

---

## FL-008 — Reference sample crashes (SIGSEGV) on the virtual device; two RCT-folly versions loaded

**Severity:** High

**Task attempted.** Play video in `vega-video-sample` on the Vega Virtual Device,
to confirm the media stack works before building against it.

**Steps taken.** Vega CLI 1.3.4, SDK 0.24.9914, VVD `vvrp-tv-arm64` OS 1.2 — all
current as of 8 September 2026, all freshly installed. Cloned
`AmazonAppDev/vega-video-sample` at HEAD, `npm install`, built Debug, installed
and launched. Selected a video.

**Expected.** Playback, using the sample's own default HLS source.

**Actual.** The UI shows "An error occurred while playing the video, please try
again later." The device produced **five crash tombstones** for
`com.amazondeveloper.keplervideoapp` across the session.

The default content is not the cause — the sample's default HLS
(`storage.googleapis.com/shaka-demo-assets/bbb-dark-truths-hls/hls.m3u8`) and MPD
(`dash.akamaized.net/envivio/dashpr/clear/Manifest.mpd`) both return HTTP 200,
and the device resolves DNS correctly.

The crash report shows:

```
CrashLang: Native
CrashReason: SIGSEGV
AppVersion: 3.24.0
PRODUCT_NAME: vvrp-tv-arm64

Thread 0 (crashed)
 0  libRCT-folly-0.83.so.0.83 + 0x142ca8
 1  libRCT-folly-0.72.so.0.72 + 0xc3642
 2  libRCT-folly-0.72.so.0.72 + 0xc2c02
 3  libRCT-folly-0.72.so.0.72 + 0xc99a2
```

**Two RCT-folly builds are loaded into the same process — 0.72 and 0.83 — and the
crashing call chain crosses between them.** The sample declares
`react-native: 0.83.0` and `@amazon-devices/react-native-kepler: ~4.0.0+rn0.83.0`.
Loading two ABI-incompatible folly builds in one address space is a plausible and
sufficient explanation for a segfault, though full root-cause confirmation would
need symbolication (blocked — see FL-009).

**Further evidence.** `vega project doctor` on the same unmodified sample reports
`SDK manifest: 1 OS versions, 2 RN versions`, and `vega project list-templates`
confirms the SDK ships both a `helloWorld` (RN 0.83) and a `helloWorld-rn72`
(RN 0.72) template — so both runtimes are present on the OS 1.2 image and
available to be loaded. Doctor also warns that nine `@amazon-devices/*` packages
in this sample are "not a managed OS-version package": `kepler-media-types`,
`kepler-ui-components`, `react-linear-gradient`,
`react-native-async-storage__async-storage`, `react-native-screens`,
`react-native-vector-icons`, `vega-carousel`, `kepler-performance-api`,
`keplerscript-commonmodules`. If any of those is built against the RN 0.72 ABI,
that is a direct route to loading both follys into one process. Notably, doctor
still concludes "All critical checks passed" for an app that segfaults on launch.

**Control test — isolates the fault to the sample, not the platform.** Scaffolded
a clean app from the SDK's own `helloWorld` template (`vega project generate -t
helloWorld`), which targets RN 0.83 and has three dependencies, none of them in
the untracked list above. Built Debug, installed and launched on the *same*
virtual device in the *same* session. It runs and stays up, and produces no
tombstone — the crash count remained at five, all of them the video sample's.

So SDK 0.24.9914, the OS 1.2 `vvrp-tv-arm64` image, and the RN 0.83 runtime are
all working correctly together. The fault is specific to `vega-video-sample`, and
the untracked-dependency warning from `vega project doctor` is the most likely
route to it.

**Workaround.** None found. This is the unmodified flagship sample on the current
SDK and the current virtual device.

**Actionable suggestion.** This is the highest-impact issue encountered: the
reference media application crashes on the reference simulator using the current
SDK, which is the first thing a new Fire TV developer will do. Please check
whether the OS 1.2 VVD image ships an RN 0.72 runtime while the SDK 0.24 samples
target RN 0.83, and either align them or document the required pairing. A version
compatibility matrix — SDK version, VVD image, RN version — published alongside
the samples would let developers diagnose this in seconds rather than through
crash-dump analysis.

---

## FL-009 — Native crash symbolication is unavailable to external developers (requires Amazon-internal Midway auth)

**Severity:** High

**Task attempted.** Symbolicate the native SIGSEGV from FL-008.

**Steps taken and what happened, in order.**

**1. The MCP tool cannot find the SDK.** `symbolicate_acr` from Amazon Devices
Builder Tools returns *"acr-report not found. Please ensure Vega SDK is installed
or set the KEPLER_SDK_PATH environment variable"* — even with the SDK correctly
installed and `vega --version` working. The MCP server does not inherit the
environment established by `~/vega/env`, so it cannot locate SDK tools.

**2. The CLI tool bootstraps its dependencies from PyPI at runtime, and fails
behind TLS inspection.** `vega exec acr-report` pip-installs into a venv at
`~/.kepler/acr_pyvenv` on each invocation. On a machine running Netskope — whose
root CA `eproxy.caadmin.netskope.com` is installed in the System keychain, as is
standard for corporate SASE deployments — every fetch fails:

```
SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED]
certificate verify failed: self-signed certificate in certificate chain'))
```

Three things make this worse than a normal proxy problem:

- **The standard workaround does not work.** `PIP_CERT`, `REQUESTS_CA_BUNDLE` and
  `SSL_CERT_FILE`, all pointing at a valid bundle containing the corporate CA,
  are ignored. The same bundle works correctly with the system `python3 -m pip`.
- **Dependencies are resolved one per invocation** — jinja2, then requests, then
  pyelftools, then urllib3, then boto3, then rich — so a developer patching this
  by hand must run the tool repeatedly to discover each next missing package.
- **The bundled venv is Python 3.10 while a current macOS system Python is 3.14**,
  so offline wheels must be fetched with explicit
  `--python-version 310 --only-binary=:all: --platform macosx_11_0_arm64`.
  Without that, binary wheels install as `cp314` and are silently unusable.

And the detail that best captures the problem: among the packages it tries to
fetch is **`pip-system-certs`** — the package that would make pip trust the
system certificate store. It cannot be installed, because pip does not trust the
system certificate store.

**3. Having got the tool running, symbolication is gated on Amazon-internal
authentication.** After manually populating the venv offline, `acr-report` starts
correctly and then stops here:

```
[sysroot_handler] - Downloading symbols this may take a few minutes...
Midway cookie not found at ~/.midway/cookie, please authenticate using mwinit.
```

Midway is Amazon's internal SSO and `mwinit` is an internal tool. **An external
developer cannot authenticate, so native crash symbolication is not available to
them at all.** Everything before this point is a nuisance; this is a wall.

**Workaround.** Read the ACR file directly — it is plain text and contains a
`<minidump_stackwalk>` section listing modules and offsets. That was sufficient to
diagnose FL-008 (two RCT-folly versions loaded in one process) without any
symbols. Unsymbolicated, but genuinely usable, and far better than nothing.

**Actionable suggestion.** In priority order:

1. **Provide an external symbolication path.** Either publish debug symbols for
   platform libraries alongside the SDK, or allow `acr-report` to source a debug
   rootfs from the connected device. As it stands, a third-party developer whose
   app crashes inside a platform library has no route to a symbolicated stack —
   which for a native crash is most of the diagnostic value. If external
   symbolication is genuinely not intended, say so in the docs rather than
   shipping a tool that appears to work and then asks for internal credentials.
2. **Vendor the Python dependencies into the SDK.** An offline-capable SDK should
   not need PyPI to read a crash report. Failing that, honour `PIP_CERT` and
   `REQUESTS_CA_BUNDLE`, and resolve all dependencies in one pass rather than one
   per run.
3. **Make the Builder Tools MCP server resolve SDK tool paths the way the CLI
   does**, or document that it must be launched with `~/vega/env` sourced.

---

## FL-010 — `vega project generate` ignores the project name for output, and exits 1 on success

**Severity:** Medium

**Task attempted.** Scaffold a clean minimal Vega app to use as a control while
diagnosing FL-008.

**Steps taken.**
```
vega project generate -t helloWorld -n sightlineprobe \
  --packageId com.sightline.probe -o .
```
run from a directory containing several other cloned projects.

**Expected.** A new project directory `./sightlineprobe/` containing the
generated app, and exit code 0.

**Actual.** Two problems.

1. **No project directory is created.** The template is written directly into
   `--outputDir` — `app.json`, `babel.config.js`, `index.js`, `jest.config.json`,
   `manifest.toml`, `metro.config.js`, `package.json`, `src/`, `test/`,
   `tsconfig.json` all landed loose in the parent directory, intermixed with
   unrelated projects. The `--name` value is used inside the generated manifest
   (`title = "... for project sightlineprobe"`) but not for the directory. Had
   this been run in a directory that already contained a `package.json` or
   `src/`, it would have overwritten them.

2. **Exit code 1 despite success.** The command prints "Success! Here are some
   common commands to try:" and then exits non-zero. Any script or CI step that
   checks the exit code treats a successful scaffold as a failure.

**Workaround.** Create the target directory first and pass it as `--outputDir`,
or move the generated files afterwards. Ignore the exit code.

**Actionable suggestion.** Create `<outputDir>/<name>/` and generate into it —
that is what the combination of `--name` and `--outputDir` implies, and it is
what every comparable scaffolding tool does. At minimum, refuse to generate into
a non-empty directory. And return 0 on success; a scaffolding command that always
reports failure cannot be used in automation.

---

## FL-011 — Documented shell method for enabling VoiceView on the Virtual Device fails with a permission error

**Severity:** High (blocking for accessibility development)

**Task attempted.** Enable VoiceView on the Vega Virtual Device in order to test
audio ducking behaviour — specifically, whether media audio ducks when a
high-priority accessibility speech stream plays, which is the core mechanic of
the app being built.

**Steps taken.** Followed the Vega accessibility FAQ, which documents three ways
to enable VoiceView, the third being:

> Via shell: `vega device shell` then run
> `vdcm set "com.amazon.devconf/system/accessibility/VoiceViewEnabled" "ENABLED"`

Tried it through `vega device run-cmd -c '...'`, through an interactive
`vega device shell` session, and through `vega exec vda shell` (the variant used
in Amazon's own support replies) — all three land in the same
"Developer mode Shell" as `uid=5000(app_user)` and all three are refused — on a freshly booted VVD (`vvrp-tv-arm64`, OS 1.2,
SDK 0.24.9914, CLI 1.3.4, developer mode on).

**Expected.** VoiceView enabled, per the documented procedure.

**Actual.** Both routes fail identically:

```
Could not set value for
'com.amazon.devconf/system/accessibility/VoiceViewEnabled':
No permission for operation
```

Reading the same key works fine (`vdcm get` returns `'DISABLED'`), so `vdcm`
itself is functioning — it is specifically the write that is refused. The reason
appears to be the shell's user context: both `run-cmd` and the "Developer mode
Shell" run as

```
uid=5000(app_user) gid=30038
groups=104(aipc),108(graphic),130(downloadmgr),256(package),
       506(package-cache),542(devmode),5000(app_user)
```

which evidently lacks the privilege to write system accessibility configuration.
The documented instruction cannot succeed as written from the shell it names.

**Also tried, and it does not help.** The Vega docs describe a deeper developer
mode than the one `vega device info` reports: `vsm developer-mode enable`, which
"provides full `inputd-cli` functionality" and reboots the device. Ran it — it
returns `enabled`, the VVD reboots — and the shell's user context is byte-for-byte
unchanged (`uid=5000(app_user)`, same groups), with `vdcm set` still refused. So
this is not a case of a developer forgetting to unlock developer mode.

**The other two documented methods are also unavailable on the VVD.** The FAQ
lists three ways to enable VoiceView. Having found the shell method refused:

- *"Navigate to Accessibility Settings → Toggle VoiceView ON"* — there is no
  Accessibility section in the virtual device's Settings. Settings contains only
  Account Settings, which in turn contains only Amazon Account and Parental
  Controls. There is nowhere to make this toggle.
- *"Hold down the Back and Menu keys for 2 seconds"* — mapped to `ESC` + `F2`
  under the VVD's documented keyboard shortcuts. Held with the window focused;
  nothing happens, and the config value stays `DISABLED` when polled.

So **all three documented methods for enabling VoiceView fail on the Vega Virtual
Device.** As far as I can determine, VoiceView cannot be enabled there at all.

Notably the underlying stack is present on the image —
`vega device installed-packages` lists `com.amazon.accessibility.tts.service` and
`com.amazon.a11y_tutorial` — so this reads as a missing switch rather than a
missing feature.

Partial scripted alternative: `inputd-cli button_press KEY_BACK|KEY_MENU
--holdDuration <ms>` can inject individual key presses, so much VVD interaction
*is* automatable. But the VoiceView toggle is a two-key chord, and there appears
to be no way to express simultaneous presses — `inputd-cli series` takes
comma-separated sequential actions and rejects `KEY_BACK+KEY_MENU` as an
unrecognised command. So the toggle specifically remains manual even though the
input tooling is otherwise good.

**Why this matters more than a typical documentation bug.** VoiceView is the
platform's primary accessibility surface, and the FAQ's own testing checklist is
built almost entirely around having it enabled — every item under "VoiceView",
plus the ducking behaviour under Troubleshooting. If the only scriptable way to
turn it on does not work, then accessibility testing on Vega is manual-only on
the simulator, and realistically requires physical hardware. For developers
outside the US, where Fire TV hardware with the current OS may be harder to
obtain, that is a meaningful barrier to building accessible apps at all.

**Actionable suggestion.** Either grant the developer-mode shell permission to
write accessibility config on the virtual device — it is a developer device by
definition, and this is exactly the kind of setting a developer needs to toggle —
or add a first-class CLI command, e.g. `vega device set-accessibility voiceview
on|off`. Failing either, correct the FAQ to state that the shell method requires
privileges the developer shell does not have, and that the UI methods are the
only ones available on the VVD. Right now the documented path fails with an error
that gives no hint the instruction itself is unusable.

---

## FL-012 — Media playback appears non-functional on the Vega Virtual Device; both official media samples fail

**Severity:** Critical (blocks all media development on the simulator)

**Task attempted.** Play a single audio file on the Vega Virtual Device.

**Environment.** Vega CLI 1.3.4, SDK 0.24.9914, VVD `vvrp-tv-arm64` OS 1.2, macOS
26.6.2 arm64. Freshly booted device, both test apps uninstalled beforehand,
`build/` deleted, clean installs throughout.

**Three independent cases, all failing.**

**1. `AmazonAppDev/vega-video-sample` — SIGSEGV.** Unmodified, current HEAD.
Playback fails and the device produces crash tombstones. Stackwalk shows
`libRCT-folly-0.83` and `libRCT-folly-0.72` both loaded in one process with the
crashing chain crossing between them. Detailed separately in FL-008.

**2. `AmazonAppDev/vega-audio-sample` — ANR on launch.** Unmodified, current HEAD,
`npm install` + `npm run build:debug` clean. `vega run-app` reports "Successfully
launched the app", but `vega device is-app-running` returns not running, the
launcher stays on screen, and the device produces tombstones:

```
CrashLang: Native
CrashReason: AppNotResponding
Crash reason: SIGQUIT
AppVersion: 3.24.0

Thread 0 (crashed)
 0  libc.so.6 + 0xe7b84
 1  libasync.so.0 + 0x9bc2
```

The app hangs during startup and is killed. It never renders.

**3. A minimal app from the SDK's own `helloWorld` template — media never
loads.** This is the informative case, because the app itself runs perfectly
stably; only media fails.

Setup mirrors `vega-audio-sample`'s `AudioHandler.ts`: `new AudioPlayer()`,
`setMediaControlFocus(componentInstance)` from
`useKeplerAppStateManager().getComponentInstance()`, then `src`, `load()`,
`play()`. Media and audio services declared in `manifest.toml` (`media.server`,
`mediametrics`, `media.playersession`, `mediabuffer`, `mediatransform`,
`gipc.uuid.*`, `audio.stream`, `audio.control`, `audio.system`, `network.service`,
plus the accessibility privilege and `net-info`).

Every source fails identically with **`MediaError.code === 4`
(`MEDIA_ERR_SRC_NOT_SUPPORTED`)**, and — the key detail — **no HTTP request ever
leaves the device**, verified against an access log on the host:

| Source | Result |
|---|---|
| `http://10.0.2.2:8099/desc.mp3` (host-served, `audio/mpeg`) | code 4, no fetch |
| `http://10.0.2.2:8099/desc.m4a` | code 4, no fetch |
| `http://10.0.2.2:8099/desc.wav` | code 4, no fetch |
| `https://d1v0fxmwkpxbrg.cloudfront.net/audio-assets/Downtown.mp3` — **`vega-audio-sample`'s own track URL** | code 4, no fetch |

Meanwhile `canPlayType()` on the same player instance reports:

```
audio/mpeg=probably  audio/mp4=probably  audio/aac=probably
audio/flac=probably  audio/ogg=probably
audio/wav=no  audio/x-wav=no  application/x-mpegURL=no  application/dash+xml=no
```

**The player reports `"probably"` for `audio/mpeg` and then rejects an MP3 as
`SRC_NOT_SUPPORTED` without attempting to fetch it.** Those two behaviours cannot
both be right.

**Systematically eliminated**, each by direct test rather than inference:

- Device state — fresh boot, both apps uninstalled, clean install
- Stale bundle — `build/` deleted; markers verified present in the aarch64 bundle
- Constructor arguments — `new AudioPlayer()`, `(SPEECH, USAGE_ACCESSIBILITY)`,
  `(SPEECH, USAGE_MEDIA)` and `(MUSIC, USAGE_MEDIA)` all identical
- Source URL, scheme and host — the sample's own HTTPS CloudFront URL fails too
- Container/codec — mp3, m4a and wav all fail
- `setMediaControlFocus()` — added, reports success, changes nothing
- Manifest declarations — diffed against `vega-audio-sample`; the probe declares
  a superset of its media modules
- Load/play sequencing — final attempt matched `AudioHandler.ts` exactly:
  construct, `setMediaControlFocus`, `initialize()`, attach listeners, set `src`
  with `autoplay = false`, no explicit `load()`, and `play()` only on `canplay`.
  Identical failure.
- Emulator audio configuration — the instance `config.ini` has no
  `hw.audioOutput` line, but the resolved `hardware-qemu.ini` shows
  `hw.audioOutput = true`, so emulator audio output is enabled
- Privileged shell — `vega exec vda shell` (used in Amazon's own support replies)
  is the same shell as `vega device shell`, same `app_user`

**Device-side audio hardware is present and correctly provisioned.**
`/proc/asound/cards` shows `virtio-snd - VirtIO SoundCard`, and
`/proc/asound/pcm` reports `VirtIO PCM 0 : playback 4 : capture 2`. So the
virtual sound device exists with four playback streams; the failure is above it.

**Workaround.** None found. Media development on the VVD appears blocked.

**Actionable suggestion.** Please verify whether media playback works at all on
the current OS 1.2 `vvrp-tv-arm64` VVD image with SDK 0.24.9914 — the two
official media samples are the obvious regression tests and both fail, in
different ways. If media playback requires physical hardware and is known not to
work on the virtual device, that needs to be stated prominently in the Vega
Virtual Device documentation: it is the difference between a developer choosing
the simulator or buying a device, and right now the docs present the VVD as a
general-purpose development target. Separately, `canPlayType()` returning
`"probably"` for a type the player will then refuse is a bug in its own right —
it is the API developers use precisely to avoid this situation.
