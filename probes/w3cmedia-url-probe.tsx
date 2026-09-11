/**
 * Verbatim reproduction of the official audio-only URL Mode example from
 * developer.amazon.com/docs/vega/0.24/media-player-select-playback
 * ("Audio-Only Playback Example"), with only an error/status readout added.
 *
 * Key difference from every previous attempt: autoplay = true, set BEFORE src.
 * No setMediaControlFocus, no load(), no play().
 */
import React, {useEffect, useRef, useState} from 'react';
import {View, Text, StyleSheet} from 'react-native';
import {AudioPlayer} from '@amazon-devices/react-native-w3cmedia';

const SRC = 'http://10.0.2.2:8099/desc.mp3';

export const App = () => {
  const audio = useRef<AudioPlayer | null>(new AudioPlayer());
  const [log, setLog] = useState<string[]>([]);
  const push = (s: string) => setLog((p) => [...p.slice(-9), s]);

  useEffect(() => {
    const p = audio.current;
    if (!p) {
      return;
    }
    (['loadstart', 'loadedmetadata', 'canplay', 'playing', 'ended', 'error'] as const).forEach(
      (e) => {
        try {
          p.addEventListener(e, () => {
            if (e === 'error') {
              push(`error code=${(p as any)?.error?.code ?? '?'}`);
            } else {
              push(e);
            }
          });
        } catch {}
      },
    );

    push('initialize()...');
    p.initialize()
      .then(() => {
        push('init ok');
        p.autoplay = true;   // <-- TRUE, before src, per the docs
        push('autoplay=true');
        p.src = SRC;
        push('src set');
      })
      .catch((err: any) => push(`init FAIL ${err?.message ?? err}`));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <View style={styles.root}>
      <Text style={styles.title}>Docs example, verbatim</Text>
      <Text style={styles.sub}>autoplay = true, set before src</Text>
      <Text style={styles.sub}>{SRC}</Text>
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
  sub: {color: '#7a8899', fontSize: 16, marginBottom: 4},
  line: {color: '#3ddc97', fontSize: 22, marginTop: 6},
});
