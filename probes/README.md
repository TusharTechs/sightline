# Probes

Two minimal apps that isolate where audio works on Vega. Both were run in the
same generated project (`helloWorld` template, same manifest, same device, same
session), so the only difference is the API used.

| Probe | API | Result on VVD |
|---|---|---|
| `pcm-audio-probe.tsx` | `keplerscript-audio-lib` → `AudioPlaybackStream.writeAsync()` | **Audible tone.** Works. |
| `w3cmedia-url-probe.tsx` | `react-native-w3cmedia` → `AudioPlayer.src` (URL Mode) | `MEDIA_ERR_SRC_NOT_SUPPORTED`, no HTTP request issued. |
| `video-url-probe.tsx` | `react-native-w3cmedia` → `VideoPlayer.src` + `KeplerVideoSurfaceView` | `MEDIA_ERR_SRC_NOT_SUPPORTED`, no HTTP request issued — **identical with and without an audio track**. |

`pcm-audio-probe.tsx` synthesises a 440 Hz sine in JavaScript and writes it as
raw 16-bit stereo PCM. It involves no network, no file, no container, no codec,
no decoder and no media server — so its success establishes that the app has
audio access and a working audio focus session, and narrows the w3cmedia failure
to the media pipeline itself.

Attributes used: `CONTENT_TYPE_SPEECH` + `USAGE_ACCESSIBILITY`, 48 kHz stereo,
`FORMAT_PCM_16_BIT`, 1024 frames/buffer, 4 buffers.


## What the video probe settled

`video-url-probe.tsx` follows the documented URL-mode pattern exactly:
`initialize()` resolves before `setSurfaceHandle()`, the handle is cached from
the view callback, and each player is deinitialized before the next is created.
It runs two cases back to back against a local HTTP server:

```
video-only  : initialized -> surface attached -> src set -> loadstart -> ERROR code=4
video+audio : initialized -> surface attached -> src set -> loadstart -> ERROR code=4
```

Three things follow, and the first two kill hypotheses that looked good:

1. **The audio track is not the cause.** The theory was that `playbin` builds an
   audio sink during preroll, so a file carrying audio would fail where a
   video-only file succeeded. Both fail identically.
2. **The surface handle is not the cause.** It attaches successfully in both
   cases, and the failure comes after.
3. **No HTTP request is issued for either file**, confirmed against the server's
   access log — the same signature as the audio case. URL mode fails before it
   opens the source, for every media type.

So the fault is in URL mode itself rather than anything specific to audio.
**MSE mode is the remaining untested path**, and it is the interesting one:
there the JavaScript layer fetches the bytes and feeds them in through
`SourceBuffer`, so it does not depend on whatever URL handling is failing here.
