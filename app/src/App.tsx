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
import {View, Text, StyleSheet} from 'react-native';
import {KeplerVideoSurfaceView} from '@amazon-devices/react-native-w3cmedia';
import {useTVEventHandler} from '@amazon-devices/react-native-kepler';
import {MsePlayer} from './media/MsePlayer';
import {DescriptionChannel} from './media/DescriptionChannel';
import {Scheduler} from './media/Scheduler';
import {UiVoice, Phrase} from './media/UiVoice';
import {dropTone} from './media/tone';
import {Cue, Mode, Timeline} from './types';

const HOST = 'http://10.0.2.2:8099';
const TIMELINE_URL = `${HOST}/timeline.json`;
const RATES = [1.0, 1.5, 2.0];

/**
 * Where description is heard.
 *
 *  tv     — solo viewing. Description plays on this device's accessibility
 *           stream and the platform ducks the film under it.
 *  phone  — co-viewing. The room hears the film untouched; description goes
 *           only to the companion device. This is not a volume setting, it is
 *           the opposite audio design, and it is the case a blind viewer
 *           watching with sighted company actually has.
 */
type AudioTarget = 'tv' | 'phone';

export const App = () => {
  const player = useRef(new MsePlayer()).current;
  const channel = useRef(new DescriptionChannel()).current;
  const scheduler = useRef<Scheduler | null>(null);
  const voice = useRef<UiVoice>(new UiVoice(HOST, channel)).current;
  const pcm = useRef<Map<number, ArrayBuffer>>(new Map()).current;
  const tone = useRef<ArrayBuffer | null>(null);
  const surfaceReady = useRef(false);
  const booted = useRef(false);
  const poll = useRef<number | null>(null);
  const report = useRef<number | null>(null);

  const [status, setStatus] = useState('starting');
  const [caption, setCaption] = useState('');
  const [dropped, setDropped] = useState(0);
  const [mode, setMode] = useState<Mode>('fit');
  const [rate, setRate] = useState(1.0);
  const [target, setTarget] = useState<AudioTarget>('tv');
  const targetRef = useRef<AudioTarget>('tv');
  const [elapsed, setElapsed] = useState(0);
  // 'undescribed' is the state that makes the work visible: the content is
  // there, nothing has described it, and the user can set that going.
  const [phase, setPhase] = useState<'loading' | 'undescribed' | 'generating' | 'playing'>('loading');
  const [genMessage, setGenMessage] = useState('');
  const genPoll = useRef<number | null>(null);

  const boot = useCallback(async () => {
    if (booted.current) return;
    booted.current = true;
    try {
      setStatus('loading timeline');
      let timeline: Timeline | null = null;
      try {
        const res = await fetch(TIMELINE_URL);
        timeline = res.ok ? await res.json() : null;
      } catch {
        timeline = null;
      }
      if (!timeline) {
        // Nothing has described this. Offer to, rather than failing.
        setPhase('undescribed');
        setStatus('no description for this video');
        await voice.load();
        await voice.say('undescribed');
        return;
      }

      setStatus('preparing audio');
      await channel.initialize();
      tone.current = dropTone();
      // Load the interface voice before anything else that might need to speak.
      await voice.load();

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
        // In co-viewing the phone schedules for itself from the same timeline;
        // this device must stay silent, or the room hears it twice.
        if (targetRef.current === 'tv') {
          scheduler.current?.tick(t, player.rate);
        }
      }, 120) as unknown as number;

      // Report the playhead so a companion device can follow it. Fire and
      // forget: the phone tolerates a missed update, and blocking playback on
      // a network round trip would be far worse than a stale reading.
      if (report.current) clearInterval(report.current);
      report.current = setInterval(() => {
        fetch(`${HOST}/position`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            t: player.currentTime,
            rate: player.rate,
            mode: targetRef.current,
            playing: !player.paused,
          }),
        }).catch(() => {});
      }, 300) as unknown as number;
      player.on('playing', () => setStatus('playing'));
      player.on('ended', () => {
        setStatus('ended');
        voice.say('ended');
      });

      setStatus('loading media');
      await player.load(`${HOST}/${timeline.media}`, timeline.mimeCodec);

      // Speak BEFORE starting playback, not over it. A blind user cannot
      // discover the controls any other way, but the full list runs twelve
      // seconds — so point at it here and let them ask for it.
      await voice.say('ready');
      await voice.say('hint');

      player.play();
      setStatus('playing');
    } catch (e: any) {
      setStatus(`FAILED: ${e?.message ?? e}`);
      voice.say('error');
    }
  }, [channel, pcm, player, voice]);

  const startGeneration = useCallback(async () => {
    setPhase('generating');
    let spoken = '';
    try {
      await fetch(`${HOST}/generate`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({media: 'content.mp4'}),
      });
    } catch {
      voice.say('gen_failed');
      setPhase('undescribed');
      return;
    }
    if (genPoll.current) clearInterval(genPoll.current);
    genPoll.current = setInterval(async () => {
      let g: any;
      try {
        g = await (await fetch(`${HOST}/generate/status`)).json();
      } catch {
        return;
      }
      setGenMessage(g.message || '');
      // Speak each stage once as it begins. Not the counts — "watched seven of
      // nine" said every few seconds would be worse than silence.
      const phrase: Record<string, Phrase> = {
        listening: 'gen_listening', watching: 'gen_watching',
        ranking: 'gen_ranking', voicing: 'gen_voicing',
      };
      if (g.stage !== spoken && phrase[g.stage]) {
        spoken = g.stage;
        voice.say(phrase[g.stage]);
      }
      if (g.ready) {
        if (genPoll.current) clearInterval(genPoll.current);
        await voice.say('gen_ready');
        booted.current = false;
        boot();
      } else if (g.stage === 'failed') {
        if (genPoll.current) clearInterval(genPoll.current);
        voice.say('gen_failed');
        setPhase('undescribed');
      }
    }, 1200) as unknown as number;
  }, [boot, voice]);

  const onSurfaceViewCreated = useCallback(
    (handle: string) => {
      player.attachSurface(handle);
      surfaceReady.current = true;
      boot();
    },
    [boot, player],
  );

  // Remote input.
  //
  // This is `useTVEventHandler` from react-native-kepler, NOT `TVEventHandler`
  // from react-native — the latter does not exist on this platform, and an
  // earlier version of this file imported it and silently registered nothing,
  // so no button did anything at all.
  //
  // `eventAction` is 0 for pressed and 1 for released; without filtering,
  // every press fires twice and each toggle immediately undoes itself.
  const onRemote = useCallback(
    (evt: any) => {
      if (!evt || evt.eventAction === 1) {
        return;
      }
      switch (evt.eventType) {
        case 'playpause':
        case 'select': {
          if (phase === 'undescribed') {
            startGeneration();
            break;
          }
          if (phase === 'generating') {
            break; // nothing useful to do; don't let a press look like a hang
          }
          const wasPaused = player.paused;
          wasPaused ? player.play() : player.pause();
          voice.say(wasPaused ? 'playing' : 'paused');
          break;
        }
        case 'right': {
          if (phase !== 'playing') {
            break;
          }
          const next = RATES[(RATES.indexOf(rate) + 1) % RATES.length];
          setRate(next);
          player.setRate(next);
          voice.say(next === 1 ? 'rate_1' : next === 1.5 ? 'rate_15' : 'rate_2');
          break;
        }
        case 'up': {
          if (phase !== 'playing') {
            break;
          }
          const next: Mode = mode === 'fit' ? 'pause' : 'fit';
          setMode(next);
          scheduler.current?.setMode(next);
          voice.say(next === 'fit' ? 'mode_fit' : 'mode_pause');
          break;
        }
        case 'down': {
          if (phase !== 'playing') {
            break;
          }
          const next: AudioTarget = target === 'tv' ? 'phone' : 'tv';
          targetRef.current = next;
          setTarget(next);
          if (next === 'phone') {
            channel.cancel();
          }
          // Announce even when moving to the phone — this is the last thing
          // this device says, and silence would be ambiguous.
          voice.say(next === 'tv' ? 'target_tv' : 'target_phone');
          break;
        }
        case 'menu':
          voice.say('help');
          break;
      }
    },
    [channel, mode, phase, player, rate, startGeneration, target, voice],
  );

  useTVEventHandler(onRemote);

  useEffect(
    () => () => {
      if (poll.current) clearInterval(poll.current);
      if (report.current) clearInterval(report.current);
      if (genPoll.current) clearInterval(genPoll.current);
      channel.destroy();
      player.destroy();
    },
    [channel, player],
  );

  return (
    <View
      style={styles.root}
      accessible
      accessibilityRole="none"
      accessibilityLabel={
        `Sightline. ${status}. ` +
        `${mode === 'fit' ? 'Fitting descriptions into gaps' : 'Pausing to describe'}. ` +
        `${rate} times speed. ` +
        `${target === 'tv' ? 'Description on this television' : 'Description on your phone'}.`
      }>
      <KeplerVideoSurfaceView
        style={styles.surface}
        onSurfaceViewCreated={onSurfaceViewCreated}
        onSurfaceViewDestroyed={(h: string) => player.detachSurface(h)}
      />
      <View style={styles.hud}>
        {/* Playback settings are meaningless until there is something to
            play with. Advertising "Fit the gaps · 1x" over a video that has no
            description yet is just noise. */}
        {phase === 'playing' ? (
          <>
            <Text style={styles.badge}>
              {mode === 'fit' ? 'Fit the gaps' : 'Pause and explain'} · {rate}x
              {dropped > 0 ? ` · ${dropped} not said` : ''}
            </Text>
            <Text style={styles.target}>
              {target === 'tv' ? '🔊 Description on this TV' : '📱 Description on phone only'}
            </Text>
          </>
        ) : (
          <Text style={styles.badge}>Sightline</Text>
        )}
        <Text style={styles.status}>
          {phase === 'generating' || phase === 'undescribed'
            ? status
            : `${status} · ${elapsed.toFixed(1)}s`}
        </Text>
        {phase === 'undescribed' ? (
          <Text style={styles.callout}>
            No audio description exists for this video.{'\n'}Press Select to create it.
          </Text>
        ) : null}
        {phase === 'generating' ? (
          <Text style={styles.callout}>Describing… {genMessage}</Text>
        ) : null}
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
  target: {color: '#3ddc97', fontSize: 17, marginTop: 6, fontWeight: '600'},
  callout: {color: '#fff', fontSize: 24, marginTop: 14, lineHeight: 32},
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
