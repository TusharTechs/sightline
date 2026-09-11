/**
 * Sightline — generated audio description for content that has none.
 *
 * The film plays over MSE; description plays concurrently on a separate
 * USAGE_ACCESSIBILITY audio stream, which the platform ducks the film under
 * automatically. The two paths are independent, which is why neither blocks the
 * other.
 *
 * Everything about WHAT gets said and WHEN is decided in Scheduler, from a
 * timeline prepared host-side. This file is wiring and remote handling.
 */
import React, {useCallback, useEffect, useRef, useState} from 'react';
import {View, Text, StyleSheet, TVEventHandler, HWEvent} from 'react-native';
import {KeplerVideoSurfaceView} from '@amazon-devices/react-native-w3cmedia';
import {MsePlayer} from './media/MsePlayer';
import {DescriptionChannel} from './media/DescriptionChannel';
import {Scheduler} from './media/Scheduler';
import {dropTone} from './media/tone';
import {Cue, Mode, Timeline} from './types';

const HOST = 'http://10.0.2.2:8099';
const TIMELINE_URL = `${HOST}/timeline.json`;
const RATES = [1.0, 1.5, 2.0];

export const App = () => {
  const player = useRef(new MsePlayer()).current;
  const channel = useRef(new DescriptionChannel()).current;
  const scheduler = useRef<Scheduler | null>(null);
  const pcm = useRef<Map<number, ArrayBuffer>>(new Map()).current;
  const tone = useRef<ArrayBuffer | null>(null);
  const surfaceReady = useRef(false);
  const booted = useRef(false);
  const poll = useRef<number | null>(null);

  const [status, setStatus] = useState('starting');
  const [caption, setCaption] = useState('');
  const [dropped, setDropped] = useState(0);
  const [mode, setMode] = useState<Mode>('fit');
  const [rate, setRate] = useState(1.0);
  const [elapsed, setElapsed] = useState(0);

  const boot = useCallback(async () => {
    if (booted.current) return;
    booted.current = true;
    try {
      setStatus('loading timeline');
      const timeline: Timeline = await (await fetch(TIMELINE_URL)).json();

      setStatus('preparing audio');
      await channel.initialize();
      tone.current = dropTone();

      // Descriptions are fetched up front. They are small, and a description
      // that arrives late is worse than one that never arrives.
      setStatus(`fetching ${timeline.cues.length} descriptions`);
      await Promise.all(
        timeline.cues.map(async (c: Cue) => {
          const buf = await (await fetch(`${HOST}/${c.pcm}`)).arrayBuffer();
          pcm.set(c.rank, buf);
        }),
      );

      setMode(timeline.mode);
      scheduler.current = new Scheduler(
        timeline,
        {
          speak: async (cue) => {
            const buf = pcm.get(cue.rank);
            setCaption(cue.text);
            const ok = buf ? await channel.speak(buf) : false;
            return ok;
          },
          tone: async () => {
            if (tone.current) await channel.speak(tone.current);
          },
          pausePlayback: () => player.pause(),
          resumePlayback: () => player.play(),
          onCue: (cue, n) => {
            setDropped(n);
            if (!cue) setTimeout(() => setCaption(''), 1200);
          },
        },
        timeline.mode,
      );

      setStatus('initialising player');
      await player.initialize();
      // Both a 'timeupdate' listener and a poll, for resolution rather than
      // reliability. Measured: timeupdate fires about every 250ms, which is
      // coarse when a description has to land inside a 1.7s gap — polling at
      // 120ms roughly halves the worst-case latency into a gap.
      //
      // (The native layer logs "No Time update event in Playing state"
      // continuously. That is end-of-stream noise, not a missing event —
      // timeupdate delivery to JS was verified.)
      player.on('timeupdate', () => {
        scheduler.current?.tick(player.currentTime, player.rate);
      });
      if (poll.current) clearInterval(poll.current);
      poll.current = setInterval(() => {
        const t = player.currentTime;
        setElapsed(t);
        scheduler.current?.tick(t, player.rate);
      }, 120) as unknown as number;
      player.on('playing', () => setStatus('playing'));
      player.on('ended', () => setStatus('ended'));

      setStatus('loading media');
      await player.load(`${HOST}/${timeline.media}`, timeline.mimeCodec);
      player.play();
      setStatus('playing');
    } catch (e: any) {
      setStatus(`FAILED: ${e?.message ?? e}`);
    }
  }, [channel, pcm, player]);

  const onSurfaceViewCreated = useCallback(
    (handle: string) => {
      player.attachSurface(handle);
      surfaceReady.current = true;
      boot();
    },
    [boot, player],
  );

  // Remote: Play/Pause toggles, Right cycles speed, Up toggles mode.
  useEffect(() => {
    const handler = (evt: HWEvent) => {
      switch (evt?.eventType) {
        case 'playPause':
        case 'select':
          player.paused ? player.play() : player.pause();
          break;
        case 'right': {
          const next = RATES[(RATES.indexOf(rate) + 1) % RATES.length];
          setRate(next);
          player.setRate(next);
          break;
        }
        case 'up': {
          const next: Mode = mode === 'fit' ? 'pause' : 'fit';
          setMode(next);
          scheduler.current?.setMode(next);
          break;
        }
      }
    };
    const sub = TVEventHandler.addListener?.(handler);
    return () => sub?.remove?.();
  }, [mode, player, rate]);

  useEffect(
    () => () => {
      if (poll.current) clearInterval(poll.current);
      channel.destroy();
      player.destroy();
    },
    [channel, player],
  );

  return (
    <View style={styles.root}>
      <KeplerVideoSurfaceView
        style={styles.surface}
        onSurfaceViewCreated={onSurfaceViewCreated}
        onSurfaceViewDestroyed={(h: string) => player.detachSurface(h)}
      />
      <View style={styles.hud}>
        <Text style={styles.badge}>
          {mode === 'fit' ? 'Fit the gaps' : 'Pause and explain'} · {rate}x
          {dropped > 0 ? ` · ${dropped} not said` : ''}
        </Text>
        <Text style={styles.status}>
          {status} · {elapsed.toFixed(1)}s
        </Text>
      </View>
      {caption ? (
        <View style={styles.captionBar}>
          <Text style={styles.caption}>{caption}</Text>
        </View>
      ) : null}
    </View>
  );
};

const styles = StyleSheet.create({
  root: {flex: 1, backgroundColor: '#000'},
  surface: {position: 'absolute', top: 0, left: 0, right: 0, bottom: 0},
  hud: {
    position: 'absolute',
    top: 28,
    left: 40,
    alignSelf: 'flex-start',
    backgroundColor: 'rgba(8,12,18,0.72)',
    borderRadius: 8,
    paddingVertical: 10,
    paddingHorizontal: 16,
  },
  badge: {color: '#fff', fontSize: 20, fontWeight: '600'},
  status: {color: '#b6c2d2', fontSize: 15, marginTop: 2},
  captionBar: {
    position: 'absolute',
    left: 60,
    right: 60,
    bottom: 54,
    backgroundColor: 'rgba(8,12,18,0.82)',
    borderRadius: 10,
    paddingVertical: 14,
    paddingHorizontal: 22,
  },
  caption: {color: '#fff', fontSize: 26, textAlign: 'center'},
});
