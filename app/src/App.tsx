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
import {View, Text, StyleSheet, Image} from 'react-native';
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
  // Control feedback appears briefly and then leaves. During playback the
  // screen belongs to the film; a permanent status panel is clutter for the
  // sighted viewer sharing the room and worth nothing to anyone else.
  const [chip, setChip] = useState('');
  // Default to the whole frame; narrowed once the timeline says otherwise.
  const [picture, setPicture] = useState({x: 0, y: 0, w: 1, h: 1});
  const chipTimer = useRef<number | null>(null);
  /**
   * Duck the film while something is spoken, then bring it back.
   *
   * `USAGE_ACCESSIBILITY` is supposed to make the platform duck other audio for
   * us, and Amazon has confirmed that is the intended behaviour — but whether
   * the virtual device emulates audio focus at all is still an open question
   * with them, and description was being drowned by the score at its peaks.
   * Since this app owns the film player as well as the description stream,
   * ducking it here is deterministic rather than hoping the platform does it.
   *
   * Ramped rather than stepped: an instant drop on a music cue is audible as a
   * glitch, and sounds like a fault rather than a feature.
   *
   * Never ducks in co-viewing — the room is listening to the film and has no
   * idea anyone's phone is talking.
   */
  const DUCK_TO = 0.22;
  const duckWhile = useCallback(
    async (fn: () => Promise<any>) => {
      if (targetRef.current !== 'tv') {
        return fn();
      }
      const ramp = async (from: number, to: number, ms: number) => {
        const steps = 6;
        for (let i = 1; i <= steps; i++) {
          player.setVolume(from + ((to - from) * i) / steps);
          await new Promise((r) => setTimeout(r, ms / steps));
        }
      };
      try {
        await ramp(1, DUCK_TO, 140);
        return await fn();
      } finally {
        await ramp(DUCK_TO, 1, 260);
      }
    },
    [player],
  );

  const flashChip = useCallback((text: string) => {
    setChip(text);
    if (chipTimer.current) clearTimeout(chipTimer.current);
    chipTimer.current = setTimeout(() => setChip(''), 2600) as unknown as number;
  }, []);

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

      if (timeline.pictureRect) {
        setPicture(timeline.pictureRect);
      }
      setMode(timeline.mode);
      scheduler.current = new Scheduler(
        timeline,
        {
          speak: async (cue) => {
            const buf = pcm.get(cue.rank);
            setCaption(cue.text);
            return duckWhile(async () =>
              buf ? await channel.speak(buf) : false,
            );
          },
          tone: async () => {
            // The tone is short and deliberately cuts through; ducking for it
            // would take longer to ramp than the tone lasts.
            if (tone.current) await channel.speak(tone.current);
          },
          pausePlayback: () => player.pause(),
          resumePlayback: () => player.play(),
          onCue: (cue, n) => {
            setDropped(n);
            // speak() now resolves when the line has actually finished, so
            // clearing here no longer cuts the caption off mid-sentence. A
            // short tail keeps it readable without drifting into the next shot.
            if (!cue) setTimeout(() => setCaption(''), 400);
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
      setPhase('playing');
      setGenMessage('');
      setStatus('playing');
    } catch (e: any) {
      setStatus(`FAILED: ${e?.message ?? e}`);
      voice.say('error');
    }
  }, [channel, duckWhile, pcm, player, voice]);

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
      // The released half of every press. The runtime field is
      // `eventKeyAction` even though the SDK's own TVTypes.d.ts documents it as
      // `eventAction`; filtering on the documented name matches nothing, so
      // every press fires twice and each toggle instantly undoes itself.
      // Both are checked so this keeps working if the docs ever become true.
      if (!evt || evt.eventKeyAction === 1 || evt.eventAction === 1) {
        return;
      }
      switch (evt.eventType) {
        // An injected or physical Enter arrives as 'enter', not 'select'.
        // Both are in the documented event union and both mean the same button.
        case 'enter':
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
          flashChip(wasPaused ? 'Playing' : 'Paused');
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
          flashChip(`${next}× speed`);
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
          flashChip(next === 'fit' ? 'Fitting the gaps' : 'Pausing to describe');
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
          flashChip(next === 'tv' ? 'Description on this TV' : 'Description on your phone');
          break;
        }
        case 'menu':
          voice.say('help');
          break;
      }
    },
    [channel, flashChip, mode, phase, player, rate, startGeneration, target, voice],
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

  const busy = phase === 'loading' || phase === 'undescribed' || phase === 'generating';

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

      {/* Playing: just the mark, quietly. Everything else is transient. */}
      {!busy ? (
        <View
          style={[
            styles.brandMini,
            // Sit inside the picture, not on the letterbox. Percentages,
            // because the surface fills the screen whatever shape the film is.
            {top: `${picture.y * 100}%`, left: `${picture.x * 100}%`},
          ]}>
          <Image source={require('./assets/mark.png')} style={styles.markMini} />
        </View>
      ) : null}

      {/* Before playback there is nothing to watch, so the panel can own the
          screen and say what is happening. */}
      {busy ? (
        <View style={styles.panel}>
          <View style={styles.panelHead}>
            <Image source={require('./assets/mark.png')} style={styles.markLarge} />
            <Text style={styles.wordmark}>Sightline</Text>
          </View>
          {phase === 'undescribed' ? (
            <>
              <Text style={styles.panelTitle}>
                No audio description exists for this video.
              </Text>
              <Text style={styles.panelSub}>Press Select to create it.</Text>
            </>
          ) : phase === 'generating' ? (
            <>
              <Text style={styles.panelTitle}>Describing this video…</Text>
              <Text style={styles.panelSub}>{genMessage || 'Starting'}</Text>
            </>
          ) : (
            <Text style={styles.panelSub}>{status}</Text>
          )}
        </View>
      ) : null}

      {chip ? (
        <View style={styles.chip}>
          <Text style={styles.chipText}>{chip}</Text>
        </View>
      ) : null}

      {caption ? (
        <View
          style={[
            styles.captionWrap,
            // Keep captions off the bar too — text on the letterbox reads as a
            // subtitle burned into the film rather than as the app speaking.
            {bottom: `${(1 - (picture.y + picture.h)) * 100}%`},
          ]}>
          <View style={styles.captionBar}>
            <View style={styles.captionAccent} />
            <Text style={styles.caption}>{caption}</Text>
          </View>
        </View>
      ) : null}
    </View>
  );
};

// TV layout. Everything is inset from the edges for overscan, text is large
// enough to read across a room, and contrast is carried by an opaque backing
// rather than by colour — the caption sits over arbitrary footage.
const SAFE = 64;
const ACCENT = '#3ddc97';

const styles = StyleSheet.create({
  root: {flex: 1, backgroundColor: '#000'},
  surface: {position: 'absolute', top: 0, left: 0, right: 0, bottom: 0},

  brandMini: {position: 'absolute', opacity: 0.55, margin: 26},
  markMini: {width: 34, height: 34, resizeMode: 'contain'},

  panel: {
    position: 'absolute',
    top: SAFE,
    left: SAFE,
    maxWidth: 900,
    backgroundColor: 'rgba(8,12,18,0.86)',
    borderRadius: 18,
    paddingVertical: 26,
    paddingHorizontal: 32,
  },
  panelHead: {flexDirection: 'row', alignItems: 'center', marginBottom: 16},
  markLarge: {width: 40, height: 40, resizeMode: 'contain', marginRight: 12},
  wordmark: {color: '#fff', fontSize: 26, fontWeight: '700', letterSpacing: -0.4},
  panelTitle: {color: '#fff', fontSize: 34, fontWeight: '600', lineHeight: 44},
  panelSub: {color: '#9fb0c2', fontSize: 22, marginTop: 8, lineHeight: 30},

  chip: {
    position: 'absolute',
    top: SAFE - 12,
    alignSelf: 'center',
    backgroundColor: 'rgba(8,12,18,0.9)',
    borderRadius: 999,
    paddingVertical: 12,
    paddingHorizontal: 26,
    borderWidth: 1,
    borderColor: 'rgba(61,220,151,0.45)',
  },
  chipText: {color: '#fff', fontSize: 21, fontWeight: '600', letterSpacing: 0.2},

  captionWrap: {
    position: 'absolute',
    left: SAFE,
    right: SAFE,
    alignItems: 'center',
    marginBottom: 22,
  },
  captionBar: {
    flexDirection: 'row',
    alignItems: 'center',
    // Narrower and shorter than a full-width bar. Cinemascope content leaves
    // a short picture, and a caption sized for 16:9 covers the subject's face.
    maxWidth: 1080,
    backgroundColor: 'rgba(6,9,13,0.86)',
    borderRadius: 14,
    paddingVertical: 15,
    paddingHorizontal: 24,
  },
  captionAccent: {
    width: 3,
    alignSelf: 'stretch',
    borderRadius: 2,
    backgroundColor: ACCENT,
    marginRight: 18,
  },
  caption: {
    flexShrink: 1,
    color: '#f4f7fa',
    fontSize: 27,
    lineHeight: 36,
    fontWeight: '500',
    letterSpacing: 0.2,
  },
});
