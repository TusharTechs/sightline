# Bug report — ready to paste into community.amazondeveloper.com/c/vega/6

**Title:**

`AudioPlayer URL Mode fails with MEDIA_ERR_SRC_NOT_SUPPORTED on VVD — app never connects to com.amazon.media.server; both official media samples also fail`

---

## Bug Description

### 1. Summary

On the Vega Virtual Device (`vvrp-tv-arm64`, OS 1.2, SDK 0.24.9914), `AudioPlayer`
URL Mode playback fails for every source I have tried. Setting `.src` produces
`MediaError.code === 4` (`MEDIA_ERR_SRC_NOT_SUPPORTED`) and **no HTTP request is
ever issued** — verified against an access log on the host machine.

Native logging shows the app connects to `com.amazon.mediametrics.service`,
`com.amazon.media.playersession.service` and `com.amazon.audio.control`, but
**never connects to `com.amazon.media.server`**, despite that service being
declared in `manifest.toml`. No `W3CMEDIA` log lines are emitted at all, even
with journal priority set to `debug`.

Separately, **both official media samples also fail on this same device**:
`vega-video-sample` crashes with SIGSEGV, and `vega-audio-sample` hangs on launch
and is killed with an ANR. That suggests this is not specific to my application.

**App Name:** sightlineprobe (pre-release, not on the Appstore — a minimal app
generated from the SDK's own `helloWorld` template)

### Bug Severity

**Blocks current development.**

---

### 2. Steps to Reproduce

1. Generate a clean project from the SDK template:
   `vega project generate -t helloWorld -n sightlineprobe --packageId com.sightline.probe`
2. Add the media library, SDK-tracked:
   `vega project install @amazon-devices/react-native-w3cmedia`
3. Declare media and audio services in `manifest.toml` (full list in §7).
4. Replace `App.tsx` with the snippet in §7 — it constructs an `AudioPlayer`,
   calls `setMediaControlFocus()`, `initialize()`, then sets `.src` and plays.
5. `npm install && npm run build:debug`
6. `vega virtual-device start`
7. `vega run-app build/aarch64-debug/sightlineprobe_aarch64.vpkg com.sightline.probe.main`

The app launches and runs stably. Only media playback fails.

---

### 3. Observed Behavior

Every source fails identically with `MediaError.code === 4`, and **no HTTP request
reaches the server**:

| Source | Content-Type | Result |
|---|---|---|
| `http://10.0.2.2:8099/desc.mp3` (host-served) | `audio/mpeg` | code 4, **no fetch** |
| `http://10.0.2.2:8099/desc.m4a` | `audio/mp4a-latm` | code 4, **no fetch** |
| `http://10.0.2.2:8099/desc.wav` | `audio/x-wav` | code 4, **no fetch** |
| `https://d1v0fxmwkpxbrg.cloudfront.net/audio-assets/Downtown.mp3` — **`vega-audio-sample`'s own track URL** | `audio/mpeg` | code 4, **no fetch** |

The "no fetch" column is measured, not inferred: a `python3 -m http.server` on the
host logs every request, and the device demonstrably can reach it (a
`gst-launch-1.0 souphttpsrc` fetch from the device shell to the same URL succeeds
and reaches EOS).

**`canPlayType()` on the same player instance contradicts this:**

```
audio/mpeg=probably   audio/mp4=probably    audio/aac=probably
audio/flac=probably   audio/ogg=probably
audio/wav=no          audio/x-wav=no
application/x-mpegURL=no   application/dash+xml=no
```

The player reports `"probably"` for `audio/mpeg` and then rejects an MP3 as
`SRC_NOT_SUPPORTED` without attempting to fetch it.

**Service connections during a playback attempt.** Captured with
`loggingctl log -f` running on-device throughout (2367 lines), after
`loggingctl config --set-level com.sightline.probe debug`, a device reboot, and
re-applying the level:

| Service | Connections observed |
|---|---|
| `com.amazon.mediametrics.service` | 15 |
| `com.amazon.media.playersession.service` | 1 |
| `com.amazon.audio.control` | 1 |
| **`com.amazon.media.server`** | **0** |
| `com.amazon.audio.stream` | 0 |
| `com.amazon.audio.system` | 0 |
| `com.amazon.mediatransform.service` | 0 |
| `com.amazon.mediabuffer.service` | 0 |

`com.amazon.mediametrics.service` starts, finds no clients, and is terminated:

```
lcm_service: appInst[51](com.amazon.mediametrics.service):
             No clients connected to the service, terminating
```

**No `W3CMEDIA` log lines are produced at any point** — no `set_src_uri`, no
`MPBBackend`, no `makeMediaError`, nothing — even at `debug` priority with the
rate limit raised to 60000.

**Both official media samples also fail on this device:**

- **`AmazonAppDev/vega-video-sample`** (unmodified, current HEAD) — SIGSEGV.
  Stackwalk shows `libRCT-folly-0.83.so.0.83` and `libRCT-folly-0.72.so.0.72`
  both loaded in one process, with the crashing chain crossing between them:
  ```
  Crash reason: SIGSEGV
  Thread 0 (crashed)
   0  libRCT-folly-0.83.so.0.83 + 0x142ca8
   1  libRCT-folly-0.72.so.0.72 + 0xc3642
   2  libRCT-folly-0.72.so.0.72 + 0xc2c02
   3  libRCT-folly-0.72.so.0.72 + 0xc99a2
  ```
- **`AmazonAppDev/vega-audio-sample`** (unmodified, current HEAD) — ANR on launch.
  `vega run-app` reports success, `vega device is-app-running` reports not
  running, the app never renders:
  ```
  CrashLang: Native
  CrashReason: AppNotResponding
  Crash reason: SIGQUIT
  Thread 0 (crashed)
   0  libc.so.6 + 0xe7b84
   1  libasync.so.0 + 0x9bc2
  ```

---

### 4. Expected Behavior

`player.src = "<url to an MP3>"` in URL Mode should fetch the resource and fire
`loadedmetadata` / `canplay`, per the W3C Media API documentation, which lists
MP3 as a supported URL Mode format — and consistent with `canPlayType()`
reporting `"probably"` for `audio/mpeg`.

---

### 4.a Possible Root Cause & Temporary Workaround

**No workaround found.**

The most likely area, based on the evidence above, is that the media playback
backend is never engaged: `com.amazon.media.server` is declared in the manifest
but receives no connection, the `W3CMEDIA` layer emits no logs, and the failure
returns before any network activity. That ordering suggests the source is
rejected before pipeline construction rather than during it.

This may be related to
[Documentation clarity for URL playback: KeplerVideoView vs KeplerVideoSurfaceView](https://community.amazondeveloper.com/t/documentation-clarity-for-url-playback-keplervideoview-vs-keplervideosurfaceview/29087),
where `MEDIA_ERR_SRC_NOT_SUPPORTED` was attributed to a missing
`setSurfaceHandle()`. That guidance is for *video* via `KeplerVideoSurfaceView`.
**Is there an equivalent surface or handle requirement for audio-only playback
via `AudioPlayer`?** Nothing in the `AudioPlayer` documentation or in
`vega-audio-sample` suggests one, but the failure signature is similar.

It may also be related to
[the `set_src_uri` / `apiStatus=50004` failure reported here](https://community.amazondeveloper.com/t/vpkg-installs-fine-on-kvd-emulator-but-fails-on-physical-hardware/28880),
§5 of that thread — same `MediaError` code 4, same "fails before any HTTP request
is issued". That report is on SDK 0.23.8358 / RN 0.72 with a flat `.ts` file; this
one is SDK 0.24.9914 / RN 0.83 with MP3/M4A/WAV. The difference is that the
reporter there *does* see `set_src_uri` reach the MPB backend and fail, whereas
here the backend appears never to be reached at all.

**Hypotheses eliminated by direct test**, so as not to waste anyone's time:

| Eliminated | How |
|---|---|
| Stale device state | Fresh VVD boot; both apps uninstalled; clean install |
| Stale bundle | `build/` deleted; markers verified present in the aarch64 bundle |
| `AudioPlayer` constructor args | `new AudioPlayer()`, `(SPEECH, USAGE_ACCESSIBILITY)`, `(SPEECH, USAGE_MEDIA)`, `(MUSIC, USAGE_MEDIA)` — all identical |
| Source URL / scheme / host | `vega-audio-sample`'s own HTTPS CloudFront URL fails too |
| Container / codec | MP3, M4A and WAV all fail |
| `setMediaControlFocus()` | Added via `useKeplerAppStateManager().getComponentInstance()`; reports success; no change |
| Load/play sequencing | Final attempt matched `AudioHandler.ts` exactly — no explicit `load()`, `play()` only on `canplay`. Identical failure |
| Manifest declarations | Diffed against `vega-audio-sample`; this app declares a superset of its media modules |
| Emulator audio disabled | Instance `config.ini` has no `hw.audioOutput` line, but resolved `hardware-qemu.ini` shows `hw.audioOutput = true` |
| Device networking | `nslookup` resolves; `gst-launch-1.0 souphttpsrc` from the device shell fetches the same URL successfully and reaches EOS |
| Missing audio hardware | `/proc/asound/cards` → `virtio-snd - VirtIO SoundCard`; `/proc/asound/pcm` → `VirtIO PCM 0 : playback 4 : capture 2` |

---

### 5. Logs or crash report

Available on request and can be attached — say which would be most useful:

- Full 2367-line `loggingctl log -f` capture across a playback attempt
- Both ACR crash reports (`vega-video-sample` SIGSEGV, `vega-audio-sample` ANR)
- Host-side HTTP access log showing zero requests during playback attempts

**Note on symbolication:** I could not symbolicate the ACRs. `vega exec acr-report`
bootstraps its Python dependencies from PyPI at runtime and fails behind corporate
TLS inspection, ignoring `PIP_CERT` / `REQUESTS_CA_BUNDLE`; after populating its
venv offline by hand it runs and then stops at
`Midway cookie not found at ~/.midway/cookie, please authenticate using mwinit`,
which is internal-only. The MCP `symbolicate_acr` tool separately fails with
"acr-report not found... ensure Vega SDK is installed", apparently because the MCP
server does not inherit `~/vega/env`. The stacks above are read directly from the
ACR files' `<minidump_stackwalk>` sections. Happy to file those as separate
issues if useful.

---

### 6. Environment

```
Active SDK Version: 0.24.9914
Vega CLI Version:   1.3.4

@amazon-devices/react-native-w3cmedia    2.3.2
@amazon-devices/react-native-kepler      4.0.1
@amazon-devices/kepler-media-controls    1.0.25
react-native                             0.83.0
react                                    19.2.0

Device: Vega Virtual Device, vvrp-tv-arm64, aarch64, simulated, developer mode on
Host:   macOS 26.6.2, arm64, Node v26.7.0
App State: Foreground
```

`/etc/os-release`:

```
OS_VERSION="1.2"
BUILD_DESC="OS 1.2 (TV Ship/101520710)"
BUILD_FINGERPRINT="1.0.152071.0(9a1d8dfa7da5d600)/101520710N:user/dev-keys"
BUILD_VARIANT="user"
```

---

### 7. Example Code Snippet

`manifest.toml` — media and audio declarations:

```toml
[needs]
[[needs.privilege]]
id = "com.amazon.network.privilege.net-info"

[wants]
[[wants.service]]
id = "com.amazon.media.server"
[[wants.service]]
id = "com.amazon.mediametrics.service"
[[wants.service]]
id = "com.amazon.media.playersession.service"
[[wants.service]]
id = "com.amazon.mediabuffer.service"
[[wants.service]]
id = "com.amazon.mediatransform.service"
[[wants.service]]
id = "com.amazon.gipc.uuid.*"
[[wants.service]]
id = "com.amazon.audio.stream"
[[wants.service]]
id = "com.amazon.audio.control"
[[wants.service]]
id = "com.amazon.audio.system"
[[wants.service]]
id = "com.amazon.network.service"
[[wants.privilege]]
id = "com.amazon.devconf.privilege.accessibility"
```

Playback code — mirrors `vega-audio-sample`'s `AudioHandler.ts`:

```tsx
import {AudioPlayer} from '@amazon-devices/react-native-w3cmedia';
import {useKeplerAppStateManager} from '@amazon-devices/react-native-kepler';

const appStateManager = useKeplerAppStateManager();
const componentInstance = appStateManager.getComponentInstance();

const player = new AudioPlayer();                       // also tried with
                                                        // (CONTENT_TYPE_SPEECH,
                                                        //  USAGE_ACCESSIBILITY)
await player.setMediaControlFocus(componentInstance);   // resolves successfully
await player.initialize();                              // resolves successfully

player.addEventListener('canplay', () => player.play());
player.addEventListener('error', () => {
  console.log('code', (player as any).error?.code);     // -> 4
});

player.src = 'http://10.0.2.2:8099/desc.mp3';           // fails here
player.autoplay = false;
```

---

### Playback Issues

- **Player SDK:** none — URL Mode only, no Shaka, no MSE
- **Player SDK Version:** n/a
- **Audio Codecs:** MP3 (LAME 128 kbps 44.1 kHz stereo), AAC-LC in M4A, PCM in WAV
- **Video Codecs:** n/a — audio only
- **Manifest Types:** none — flat files over HTTP/HTTPS
- **Architecture:** aarch64 (also builds armv7 and x86_64; tested aarch64)

**Content URL:** `https://d1v0fxmwkpxbrg.cloudfront.net/audio-assets/Downtown.mp3`
is `vega-audio-sample`'s own track and reproduces the failure, so no private URL
is needed to reproduce. The local files were generated with macOS `say` +
`ffmpeg` and served with `python3 -m http.server`; I can supply them if wanted.

**Special headers:** none. Plain `GET`, no auth, no tokens, no geo restriction.

---

### Additional Context

The specific questions that would unblock me:

1. **Is media playback expected to work on the Vega Virtual Device at all**, or is
   physical hardware required? My project is entirely audio behaviour, so if the
   VVD cannot do media I need to order a device rather than keep debugging. The
   VVD documentation presents it as a general-purpose development target and
   doesn't say otherwise.
2. **Is there a surface/handle prerequisite for audio-only `AudioPlayer` playback**,
   analogous to `setSurfaceHandle()` for video? If so it isn't in the `AudioPlayer`
   docs and isn't in `vega-audio-sample`.
3. **Should `com.amazon.media.server` receive a connection** when `.src` is set on
   an `AudioPlayer`? It is declared in the manifest but never contacted.
4. Separately — **`canPlayType()` returning `"probably"` for a type the player then
   refuses** looks like a bug in its own right, since that API exists precisely to
   let apps avoid this.

Relatedly, I have not been able to enable VoiceView on the VVD by any of the three
methods in the accessibility FAQ (Settings has no Accessibility section; the
Back+Menu chord doesn't fire; `vdcm set` returns "No permission for operation" via
`vega device shell`, `vega device run-cmd` and `vega exec vda shell` alike, and
`vsm developer-mode enable` doesn't change the shell's `uid=5000(app_user)`
context). Happy to raise that separately if it isn't the same underlying area.
