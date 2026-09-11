# Forum update — ready to paste into topic 29117

**Status first: I am unblocked and this is no longer urgent for me.** My app now
uses MSE and plays correctly. Everything below is diagnosis rather than
escalation — posting it because it localises the fault a long way, and because a
few of the dead ends cost me days that better documentation would have saved.

---

## 1. The short version

Three paths, same app, same device, same session, same source footage. Only the
way the bytes reach the player differs:

| Path | HTTP request issued? | Result |
|---|---|---|
| `AudioPlayer.src = <url>` (URL mode) | **none, ever** | `MEDIA_ERR_SRC_NOT_SUPPORTED` |
| `VideoPlayer.src = <url>` (URL mode, with surface) | **none, ever** | `MEDIA_ERR_SRC_NOT_SUPPORTED` |
| `MediaSource` + `SourceBuffer.appendBuffer()` | yes — 3,995,867 bytes, confirmed in my server's access log | `canplay` → `playing`, audio audible |

So the decoders, the media pipeline, the video sink, the audio sink, the surface
handle and the app's network access are all demonstrably working. The same
player instance plays the same footage when the bytes are handed to it directly.

The MSE run, with **no Shaka, hls.js or dash.js involved** — raw `MediaSource`:

```
isTypeSupported('video/mp4; codecs="avc1.64001F,mp4a.40.2"')  -> true
sourceopen -> addSourceBuffer ok -> fetched 3995867 bytes
-> appendBuffer -> updateend -> endOfStream
-> loadedmetadata -> canplay -> playing        (audio audible on the host)
```

## 2. Hypotheses I eliminated, so nobody repeats them

**It is not the audio track.** I expected `playbin` to build an audio sink
during preroll, so a file carrying audio would fail where a video-only file
succeeded. I tested both in URL mode: identical failure, `loadstart` then code 4.
Both play fine over MSE.

**It is not the surface handle.** Following the URL-mode pattern exactly —
`initialize()` resolved before `setSurfaceHandle()`, handle cached from
`onSurfaceViewCreated` — the surface attaches successfully and the failure comes
after it.

**It is not device audio, and not my manifest.** A second probe in the same
project, same manifest, synthesises a sine wave in JavaScript and writes it as
raw PCM through `keplerscript-audio-lib`:

```ts
builder.setAudioConfig({ sampleRate: SAMPLE_RATE_48_KHZ,
                         channelMask: CHANNEL_STEREO,
                         format: FORMAT_PCM_16_BIT });
builder.setAudioAttributes({ contentType: CONTENT_TYPE_SPEECH,
                             usage: USAGE_ACCESSIBILITY,
                             flags: FLAG_NONE });
const stream = await builder.buildAsync();
await stream.startAsync();
await stream.writeAsync(pcm);
```

That is **audible**. So the app is granted audio access and gets a working
`USAGE_ACCESSIBILITY` focus session with the manifest as filed.

**`fetch()` works from the app.** The probes report progress by fetching my host
and download their media the same way. URL mode issuing *no request at all* is
therefore inside the platform's URL handling, not a networking problem at my end.

**Please also disregard the "emulator audio disabled" line of enquiry** from my
original report. Device audio works — the boot animation's chime is audible, and
`animationservice` logs `Audio Focus 1 is granted` and `initial audio frame
presented to hardware` on every boot.

## 3. The question this narrows to

What happens between `player.src = <url>` and the source element being opened,
such that it fails with `MEDIA_ERR_SRC_NOT_SUPPORTED`, issues no HTTP request,
and emits no `W3CMEDIA` log line at all — even at `debug` with the rate limit
raised to 60000?

`canPlayType()` on the same instance returns `"probably"` for the same type, so
format negotiation is not where it stops.

## 4. Documentation gaps — the part I think is most worth acting on

These cost me real time, and each is a small fix.

**a. There is no guidance for "URL mode does not work".** The docs present URL
mode and MSE as a convenience/capability tradeoff. Nothing suggests trying MSE to
isolate a URL-mode failure, and that single step would have saved me several
days. A troubleshooting line — *if URL playback fails, test the same content via
MSE to determine whether the fault is in source handling or in the pipeline* —
would be worth a lot.

**b. MSE is documented only via Shaka / hls.js / dash.js.** For non-adaptive,
non-DRM content, raw `MediaSource` + `SourceBuffer` is about fifteen lines, needs
no player library, and avoids the Vega-patched `dist` build process entirely.
That option is not mentioned anywhere I could find. Two details that are easy to
get wrong and are not stated:

- the content must be **fragmented** MP4 — a normal MP4 will not append
  (`ffmpeg -i in.mp4 -c copy -movflags +frag_keyframe+empty_moov+default_base_moof out.mp4`)
- attachment is via **`srcObject`**, not `src`

**c. `vega device run-cmd` is a sandboxed app context, and nothing says so.**
It runs as `uid=5000(app_user)` with no component instance and no service grants.
Platform probes run from there return confident false negatives:

| Probe | Reports | Actual |
|---|---|---|
| `gst-launch-1.0 audiotestsrc ! novaaudiosink` | `AudioServer is unavailable` | audio server running fine |
| `ls /dev/snd` | `No such file or directory` | exists, namespaced away |
| `ps aux \| grep audio` | nothing | running, not visible |

I concluded from those three that the virtual device had no audio output at all,
and nearly filed it as a root cause here. The device had been playing an audible
boot chime the whole time. A note in the debugging docs saying the shell is a
sandboxed app context — and, better, a permission-denied path that says so
rather than reporting the resource as absent — would prevent this entirely.

**d. Service declarations cannot be verified in either direction.** Missing
services under `[wants]` fail silently, which the guidance already acknowledges.
But `[needs]` does not escalate it: a required service that cannot possibly exist
still validates, installs, launches and runs —

```toml
[[needs.service]]
id = "com.amazon.definitely.not.a.real.service"
```
```
manifest validation found 0 errors
Installing/Updating ... success
com.sightline.probe.main is running
```

So there is no way for an app to confirm a service was granted. Validating
service IDs at build time, where the manifest is already parsed, would close
this — or a `vega device installed-services` command.

**e. The audio-only example does not compile.** In
[Selecting the Playback Mode](https://developer.amazon.com/docs/vega/0.24/media-player-select-playback),
the snippet imports `VideoPlayer` and types the ref as `useRef<VideoPlayer | null>(...)`,
then constructs `new AudioPlayer()`, which is never imported.

## 5. On the physical device comparison

I still don't have a Fire TV Stick 4K Select, so I can't run that isolation. If
it would help your team, I'm happy to share the two probe apps — one that fails
in URL mode and one that plays the same content over MSE — as a minimal
reproduction.

Thanks for the attention on this. The platform has been good to build on once
past these; the media documentation is the part I'd point at.
