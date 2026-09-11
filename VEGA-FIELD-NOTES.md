# Vega field notes

Practical notes from building a Fire TV (Vega OS) app, covering things that cost
us hours and are not in the documentation or the developer forum. Everything
here was verified on this project — SDK 0.24.9914, CLI 1.3.4, React Native 0.83,
Vega Virtual Device `vvrp-tv-arm64`, OS 1.2.

This is the *how do I get this done* companion to `FRICTION-LOG.md`, which is the
*please fix this* version of the same journey.

---

## 1. Where your `console.log` actually goes

Not to Metro. Metro shows only `BUNDLE ./index.js`. Vega routes app logging to
the **React Native output channel in VS Code**.

We spent a day building HTTP telemetry to get values off the device before
finding this. Check the output channel first.

---

## 2. Getting native logs off the device

`loggingctl` has **three independent gates**, and missing any one gives you a
silent or truncated log:

```bash
vega device run-cmd -c "loggingctl config --set-level <your.package.id> debug"
vega device reboot                 # the level only takes effect after a reboot
vega device run-cmd -c "loggingctl config --set-rate 60000"   # or you get rate-limited
vega device run-cmd -c "loggingctl log -f"                    # -v filters by package
```

Set the level, reboot, re-apply, *then* raise the rate limit. Without the rate
change, a busy boot silently drops the lines you need.

For a bulk pull instead of a stream:

```bash
vega device get-log-info                                    # what exists
vega device copy-logs --artifact system/var_log --directory ./logs
vega device copy-logs --artifact SYSTEM_TOMBSTONE/acr --directory ./logs
```

`system/var_log` is where boot-time service behaviour lives and is often more
informative than the app's own log.

---

## 3. `vega device run-cmd` is a sandboxed app context, not a system shell

This is the single most expensive thing we learned.

```bash
vega device run-cmd -c "id"
# uid=5000(app_user) gid=30038 groups=...
```

It runs as a restricted user in a sandbox with no component instance, no audio
focus session, and no manifest-granted service access. **Platform probes run
from here return misleading negatives**, with no indication that access — rather
than the feature — is what failed:

| Probe from `run-cmd` | Reports | Reality |
|---|---|---|
| `gst-launch-1.0 audiotestsrc ! novaaudiosink` | `AudioServer is unavailable` | Audio server running fine |
| `ls /dev/snd` | `No such file or directory` | Device nodes exist, namespaced away |
| `ps aux \| grep audio` | nothing | Daemons running, not visible |

We concluded from those three that the virtual device had no audio at all. It
had been playing an audible boot chime the whole time.

**Rule: verify platform state against observable device behaviour — audible
output, log lines from system services — never against a `run-cmd` probe.**

---

## 4. Manifest service declarations are not verifiable, in either direction

- Services missing under `[wants]` fail **silently** — no error, no warning, the
  feature just does nothing.
- `[needs]` does **not** fix this. A required service that cannot possibly exist
  installs, launches and runs:

```toml
[[needs.service]]
id = "com.amazon.definitely.not.a.real.service"
```

```
manifest validation found 0 errors
Installing/Updating ... success
com.example.app.main is running
```

So you cannot confirm from inside the app whether a service was granted. Don't
spend time debugging manifest declarations against a symptom — copy the list
from the media-player setup docs, then test the *behaviour* instead.

---

## 5. There are two independent audio paths, and they fail independently

| Path | Package | What it takes |
|---|---|---|
| W3C media | `@amazon-devices/react-native-w3cmedia` | a URL or MSE buffers |
| Low-level audio | `@amazon-devices/keplerscript-audio-lib` | raw PCM you write yourself |

On our virtual device `AudioPlayer.src` fails with `MEDIA_ERR_SRC_NOT_SUPPORTED`
and issues no HTTP request at all, while `AudioPlaybackStream.writeAsync()`
produces audible sound from the same app, same manifest, same session.

**If audio isn't working, test the low-level path before assuming the device is
broken.** A 30-second probe that synthesises a sine in JavaScript and writes it
as PCM removes the network, the file, the container, the codec, the decoder and
the media server from the picture in one step:

```ts
const builder = new AudioPlaybackStreamBuilder();
builder.setAudioConfig({
  sampleRate: AudioSampleRate.SAMPLE_RATE_48_KHZ,
  channelMask: AudioChannelMask.CHANNEL_STEREO,
  format:     AudioSampleFormat.FORMAT_PCM_16_BIT,
});
builder.setAudioAttributes({
  contentType: AudioContentType.CONTENT_TYPE_SPEECH,
  usage:       AudioUsageType.USAGE_ACCESSIBILITY,
  flags:       AudioFlags.FLAG_NONE,
});
const stream = await builder.buildAsync();
await stream.startAsync();
await stream.writeAsync(pcmArrayBuffer);   // 16-bit 48kHz stereo interleaved
```

Working probes for both paths are in `probes/`.

**Format matters:** the platform sink reports support for
`audio/x-raw, format=S16LE, layout=interleaved, rate=48000, channels=2`. Feed it
anything else and decode/resample before the device, not on it.

**`USAGE_ACCESSIBILITY` ducks other audio automatically** — confirmed by Amazon
as intended behaviour. If you want manual control, `setDuckingPolicy(EXPLICIT)`
plus `duckVolumeAsync()`.

---

## 5a. If URL mode fails, try MSE before assuming the device is broken

On our virtual device `player.src = "<url>"` fails for **every** media type —
audio, video-only, video with audio — with `MEDIA_ERR_SRC_NOT_SUPPORTED` and
**no HTTP request issued at all**. The same player instance, in the same app and
session, plays the same footage when the bytes are fed in through MSE.

You do not need Shaka or hls.js to test this. Raw `MediaSource` is about fifteen
lines and keeps the test about the platform rather than a player library:

```ts
const player = new VideoPlayer();
await player.initialize();
player.setSurfaceHandle(surfaceHandle);      // after initialize() resolves

const ms = new MediaSource();
ms.addEventListener('sourceopen', async () => {
  const sb = ms.addSourceBuffer('video/mp4; codecs="avc1.64001F,mp4a.40.2"');
  const buf = await (await fetch(url)).arrayBuffer();
  sb.addEventListener('updateend', () => { ms.endOfStream(); player.play(); });
  sb.appendBuffer(new Uint8Array(buf));
});
(player as any).srcObject = ms;              // srcObject, not src
```

Two things that will waste your time otherwise:

- **The content must be fragmented.** A normal MP4 will not append. Produce one
  with
  `ffmpeg -i in.mp4 -c copy -movflags +frag_keyframe+empty_moov+default_base_moof out.mp4`
- **Get the codec string right.** `avc1.<profile><constraints><level>` in hex —
  H.264 High profile at level 3.1 is `avc1.64001F`. Add `,mp4a.40.2` for AAC-LC.
  `MediaSource.isTypeSupported()` will tell you before you append.

Working probes for both paths are in this repository's `probes/` directory.

---

## 6. Screenshots and input on the virtual device

Keyboard mapping, straight from the launch arguments:

| Remote | Key |
|---|---|
| Select | `Enter` |
| D-pad | Arrow keys |
| Back | `Esc` |
| Home | `F1` |
| Menu | `F2` |
| Rewind / Play-Pause / Fast-forward | `F3` / `F4` / `F5` |

If you script screenshots on macOS, **guard on the frontmost window**. We twice
captured unrelated windows before adding:

```bash
FRONT=$(osascript -e 'tell application "System Events" to get name of first process whose frontmost is true')
[ "$FRONT" = "vega-virtual-device" ] || { echo "ABORT: frontmost is $FRONT"; exit 1; }
```

---

## 7. Choosing a sample to start from

- `hello-world-fire-tv-react-native` is **Fire OS**, not Vega — Expo /
  `react-native-tvos`, no `manifest.toml`, cannot run on the virtual device. The
  resources page lists Vega and Fire OS samples together without labelling them.
- `react-native-multi-tv-app-sample` uses `react-native-video`, which the Vega
  media guidance explicitly steers you away from.
- `vega-video-sample` crashes with SIGSEGV on a stock virtual device, with
  `libRCT-folly-0.83` and `libRCT-folly-0.72` both loaded in one process.
- For a clean start, generate rather than clone:
  `vega project generate -t helloWorld -n myapp --packageId com.example.myapp`
  (note: it ignores the project name for the output directory, and exits 1 on
  success — check for the directory, not the exit code).

---

## 8. Native crashes are not symbolicatable from outside Amazon

`acr-report` stops at `Midway cookie not found` — Amazon-internal SSO. Read the
stack by hand instead; ACR files contain a `<minidump_stackwalk>` section giving
crash reason, faulting thread, and loaded modules with offsets. That is enough to
identify *which* libraries are involved — it is how the dual RCT-folly load above
was found — but not where in them.

---

## 9. Things we confirmed with Amazon

- Physical hardware is **not** required for the hackathon (though the docs
  require validation on a Fire TV Stick 4K Select before Appstore submission).
- Audio-only playback needs **no** surface handle — `setSurfaceHandle()` and
  `KeplerVideoSurfaceView` are video-only requirements.
- `USAGE_ACCESSIBILITY` ducking media is intended, documented behaviour.
- Vega has **no app-level speech-to-text**. The only supported paths are the
  platform keyboard's microphone on a focused `TextInput`, or the Alexa button.
  Plan voice input off-device.

---

## Open at time of writing

- `AudioPlayer` URL mode returning `MEDIA_ERR_SRC_NOT_SUPPORTED` with no HTTP
  request issued, while the device's audio works and the low-level path plays.
  Filed; under investigation by Amazon.
- Whether audio focus and ducking are emulated faithfully on the virtual device.
- Whether VoiceView can be enabled on the virtual device by any means — all
  three documented methods fail there.
