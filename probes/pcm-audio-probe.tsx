/**
 * Probe: can ANY audio be produced by this app?
 *
 * Deliberately removes every variable that w3cmedia URL Mode involves:
 *   no network, no file, no container, no codec, no decoder, no media server.
 * A sine wave is synthesised in JS and written straight to an
 * AudioPlaybackStream as raw PCM.
 *
 * If this makes sound, the app CAN reach the audio server and the w3cmedia
 * failure is specific to the media pipeline.
 * If it does not, the app is denied audio wholesale.
 */
import React, {useEffect, useRef, useState} from 'react';
import {View, Text, StyleSheet} from 'react-native';
import {
  AudioPlaybackStreamBuilder,
  AudioPlaybackStream,
  AudioSampleRate,
  AudioChannelMask,
  AudioSampleFormat,
  AudioContentType,
  AudioUsageType,
  AudioFlags,
} from '@amazon-devices/keplerscript-audio-lib';

const RATE = 48000;
const CHANNELS = 2;
const SECONDS = 3;
const TONE_HZ = 440;

/** 16-bit stereo interleaved sine, as an ArrayBuffer. */
function makeSine(): ArrayBuffer {
  const frames = RATE * SECONDS;
  const buf = new ArrayBuffer(frames * CHANNELS * 2);
  const view = new DataView(buf);
  for (let i = 0; i < frames; i++) {
    const s = Math.sin((2 * Math.PI * TONE_HZ * i) / RATE) * 0.3 * 32767;
    const v = Math.max(-32768, Math.min(32767, Math.round(s)));
    view.setInt16(i * 4, v, true);
    view.setInt16(i * 4 + 2, v, true);
  }
  return buf;
}

export const App = () => {
  const stream = useRef<AudioPlaybackStream | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const push = (s: string) => setLog((p) => [...p.slice(-11), s]);

  useEffect(() => {
    (async () => {
      try {
        const builder = new AudioPlaybackStreamBuilder();
        builder.setAudioConfig({
          sampleRate: AudioSampleRate.SAMPLE_RATE_48_KHZ,
          channelMask: AudioChannelMask.CHANNEL_STEREO,
          format: AudioSampleFormat.FORMAT_PCM_16_BIT,
        });
        builder.setAudioAttributes({
          contentType: AudioContentType.CONTENT_TYPE_SPEECH,
          usage: AudioUsageType.USAGE_ACCESSIBILITY,
          flags: AudioFlags.FLAG_NONE,
        });
        builder.setFramesPerBuffer(1024);
        builder.setBufferCount(4);
        push('builder configured');

        const s = await builder.buildAsync();
        stream.current = s;
        push('buildAsync OK');

        const chk = await s.initCheckAsync();
        push(`initCheck=${chk}`);

        const started = await s.startAsync();
        push(`startAsync=${started}`);

        const pcm = makeSine();
        push(`pcm ${pcm.byteLength} bytes`);

        // write in chunks so we can see progress / a stall
        const CHUNK = 1024 * 4 * 8; // 8 buffers' worth
        let off = 0;
        let writes = 0;
        let total = 0;
        while (off < pcm.byteLength) {
          const slice = pcm.slice(off, Math.min(off + CHUNK, pcm.byteLength));
          const st = await s.writeAsync(slice);
          writes++;
          if (st > 0) {
            total += st;
          } else {
            push(`write FAILED status=${st} at chunk ${writes}`);
            break;
          }
          off += CHUNK;
        }
        push(`writes=${writes} bytes=${total}`);
        push(total > 0 ? 'DONE — listen for a tone' : 'DONE — nothing written');
      } catch (e: any) {
        push(`THREW ${e?.message ?? JSON.stringify(e)}`);
      }
    })();
  }, []);

  return (
    <View style={styles.root}>
      <Text style={styles.title}>Raw PCM probe</Text>
      <Text style={styles.sub}>keplerscript-audio-lib · 440Hz · no network, no codec</Text>
      {log.map((l, i) => (
        <Text key={i} style={styles.line}>
          {l}
        </Text>
      ))}
    </View>
  );
};

const styles = StyleSheet.create({
  root: {flex: 1, backgroundColor: '#0b0f14', padding: 44},
  title: {color: '#fff', fontSize: 34, fontWeight: '600'},
  sub: {color: '#7a8899', fontSize: 16, marginBottom: 10},
  line: {color: '#3ddc97', fontSize: 20, marginTop: 4},
});
