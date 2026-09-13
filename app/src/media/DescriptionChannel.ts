/**
 * The description channel.
 *
 * A second, concurrent audio stream carrying generated description, declared as
 * CONTENT_TYPE_SPEECH + USAGE_ACCESSIBILITY. The platform ducks other audio for
 * an accessibility stream automatically — confirmed by Amazon as intended — so
 * the film quietens under the description without us mixing anything.
 *
 * Deliberately NOT w3cmedia. This path works on the virtual device where URL
 * mode does not, it needs no media server, and raw PCM gives frame-accurate
 * timing, which everything about gap budgeting depends on. See HANDOFF.md.
 *
 * Audio is 16-bit 48kHz stereo interleaved — the format the platform sink
 * reports. All decoding happens host-side; the device is handed samples.
 */
import {
  AudioPlaybackStream,
  AudioPlaybackStreamBuilder,
  AudioSampleRate,
  AudioChannelMask,
  AudioSampleFormat,
  AudioContentType,
  AudioUsageType,
  AudioFlags,
} from '@amazon-devices/keplerscript-audio-lib';

const FRAMES_PER_BUFFER = 1024;
const BUFFER_COUNT = 4;
/** Write in chunks so a long line can be interrupted between them. */
const CHUNK_BYTES = FRAMES_PER_BUFFER * 4 * 8;
const BYTES_PER_SECOND = 48000 * 2 * 2;   // 48kHz, stereo, 16-bit

export class DescriptionChannel {
  private stream: AudioPlaybackStream | null = null;
  private speaking = false;
  private cancelled = false;

  async initialize(): Promise<void> {
    const b = new AudioPlaybackStreamBuilder();
    b.setAudioConfig({
      sampleRate: AudioSampleRate.SAMPLE_RATE_48_KHZ,
      channelMask: AudioChannelMask.CHANNEL_STEREO,
      format: AudioSampleFormat.FORMAT_PCM_16_BIT,
    });
    b.setAudioAttributes({
      contentType: AudioContentType.CONTENT_TYPE_SPEECH,
      usage: AudioUsageType.USAGE_ACCESSIBILITY,
      flags: AudioFlags.FLAG_NONE,
    });
    b.setFramesPerBuffer(FRAMES_PER_BUFFER);
    b.setBufferCount(BUFFER_COUNT);
    this.stream = await b.buildAsync();
    await this.stream.startAsync();
  }

  get isSpeaking(): boolean {
    return this.speaking;
  }

  /** Abandon the line currently being spoken, at the next chunk boundary. */
  cancel(): void {
    this.cancelled = true;
  }

  /**
   * Speak one line. Resolves when the audio has actually FINISHED PLAYING.
   *
   * `writeAsync` returns once bytes are accepted into the buffer, not once they
   * have been heard, so resolving on the last write reports the line as done
   * while it is still being spoken. Callers use this to decide when to clear the
   * caption and when to restore the film's volume, and both were happening
   * mid-sentence.
   *
   * There is no "drained" callback, so the remaining time is derived from the
   * byte count: PCM at a known rate is exactly as long as its length says.
   *
   * Overlapping speech is never correct here — two descriptions at once is
   * worse than one missed — so a call while already speaking is dropped rather
   * than queued.
   */
  async speak(pcm: ArrayBuffer): Promise<boolean> {
    if (!this.stream || this.speaking) {
      return false;
    }
    this.speaking = true;
    this.cancelled = false;
    const started = Date.now();
    const playMs = (pcm.byteLength / BYTES_PER_SECOND) * 1000;
    try {
      for (let off = 0; off < pcm.byteLength; off += CHUNK_BYTES) {
        if (this.cancelled) {
          return false;
        }
        const end = Math.min(off + CHUNK_BYTES, pcm.byteLength);
        const status = await this.stream.writeAsync(pcm.slice(off, end));
        if (typeof status === 'number' && status < 0) {
          return false;
        }
      }
      // Writing finished; playback has not. Wait out the remainder.
      const left = playMs - (Date.now() - started);
      if (left > 0) {
        await new Promise((r) => setTimeout(r, left));
      }
      return true;
    } finally {
      this.speaking = false;
    }
  }

  async destroy(): Promise<void> {
    try {
      await this.stream?.stopAsync();
      if (this.stream) {
        await AudioPlaybackStreamBuilder.destroyAsync(this.stream);
      }
    } catch {}
    this.stream = null;
  }
}
