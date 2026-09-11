# Probes

Two minimal apps that isolate where audio works on Vega. Both were run in the
same generated project (`helloWorld` template, same manifest, same device, same
session), so the only difference is the API used.

| Probe | API | Result on VVD |
|---|---|---|
| `pcm-audio-probe.tsx` | `keplerscript-audio-lib` → `AudioPlaybackStream.writeAsync()` | **Audible tone.** Works. |
| `w3cmedia-url-probe.tsx` | `react-native-w3cmedia` → `AudioPlayer.src` (URL Mode) | `MEDIA_ERR_SRC_NOT_SUPPORTED`, no HTTP request issued. |

`pcm-audio-probe.tsx` synthesises a 440 Hz sine in JavaScript and writes it as
raw 16-bit stereo PCM. It involves no network, no file, no container, no codec,
no decoder and no media server — so its success establishes that the app has
audio access and a working audio focus session, and narrows the w3cmedia failure
to the media pipeline itself.

Attributes used: `CONTENT_TYPE_SPEECH` + `USAGE_ACCESSIBILITY`, 48 kHz stereo,
`FORMAT_PCM_16_BIT`, 1024 frames/buffer, 4 buffers.
