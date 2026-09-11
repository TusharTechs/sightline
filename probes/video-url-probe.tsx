/**
 * Video playback probe.
 *
 * Determines whether VideoPlayer URL mode works on this device, and whether the
 * presence of an audio track is what breaks it — playbin constructs its audio
 * sink during preroll, so a file WITH audio can fail where a video-only file
 * succeeds, and that difference is the whole question.
 *
 * Follows the documented URL-mode pattern exactly: initialize() resolves BEFORE
 * setSurfaceHandle(), surface handle cached from the view callback, and each
 * player deinitialized before the next is created (Vega allows one decoder
 * session at a time).
 *
 * Results are beaconed to the host's HTTP server because app console.log goes
 * to the VS Code output channel, which is not readable from a scripted run.
 */
import React, {useCallback, useEffect, useRef, useState} from 'react';
import {View, Text, StyleSheet} from 'react-native';
import {VideoPlayer, KeplerVideoSurfaceView} from '@amazon-devices/react-native-w3cmedia';

const HOST = 'http://10.0.2.2:8099';
const CASES = [
  {name: 'video-only', url: `${HOST}/video-only.mp4`},
  {name: 'video+audio', url: `${HOST}/video-audio.mp4`},
];
const SETTLE_MS = 12000;

const beacon = (msg: string) => {
  try {
    fetch(`${HOST}/PROBE/${encodeURIComponent(msg)}`).catch(() => {});
  } catch {}
};

export const App = () => {
  const surface = useRef<string | null>(null);
  const started = useRef(false);
  const [lines, setLines] = useState<string[]>([]);

  const log = useCallback((s: string) => {
    setLines((p) => [...p.slice(-12), s]);
    beacon(s);
  }, []);

  const runCase = useCallback(
    (c: {name: string; url: string}) =>
      new Promise<void>((resolve) => {
        let player: VideoPlayer | null = new VideoPlayer();
        let done = false;
        const finish = async (verdict: string) => {
          if (done) return;
          done = true;
          log(`${c.name}: ${verdict}`);
          try {
            await player?.deinitialize();
          } catch (e: any) {
            log(`${c.name}: deinit threw ${e?.message ?? e}`);
          }
          player = null;
          resolve();
        };

        const timer = setTimeout(() => finish('TIMEOUT — no canplay, no error'), SETTLE_MS);

        (async () => {
          try {
            await player!.initialize();
            log(`${c.name}: initialized`);

            (['loadstart', 'loadedmetadata', 'canplay', 'playing', 'ended'] as const).forEach(
              (evt) =>
                player!.addEventListener(evt, () => {
                  log(`${c.name}: ${evt}`);
                  if (evt === 'playing') {
                    clearTimeout(timer);
                    setTimeout(() => finish('PLAYING — video works'), 1500);
                  }
                }),
            );
            player!.addEventListener('error', () => {
              clearTimeout(timer);
              finish(`ERROR code=${(player as any)?.error?.code ?? '?'}`);
            });

            if (surface.current) {
              player!.setSurfaceHandle(surface.current);
              log(`${c.name}: surface attached`);
            } else {
              log(`${c.name}: NO SURFACE HANDLE`);
            }
            player!.autoplay = true;
            player!.src = c.url;
            log(`${c.name}: src set`);
          } catch (e: any) {
            clearTimeout(timer);
            finish(`THREW ${e?.message ?? e}`);
          }
        })();
      }),
    [log],
  );

  const onSurfaceViewCreated = useCallback(
    async (handle: string) => {
      surface.current = handle;
      log(`surface created`);
      if (started.current) return;
      started.current = true;
      for (const c of CASES) {
        await runCase(c);
      }
      log('ALL CASES DONE');
    },
    [log, runCase],
  );

  const onSurfaceViewDestroyed = useCallback((handle: string) => {
    surface.current = null;
    log('surface destroyed');
  }, [log]);

  useEffect(() => {
    beacon('APP START');
  }, []);

  return (
    <View style={styles.root}>
      <KeplerVideoSurfaceView
        style={styles.surface}
        onSurfaceViewCreated={onSurfaceViewCreated}
        onSurfaceViewDestroyed={onSurfaceViewDestroyed}
      />
      <View style={styles.overlay}>
        <Text style={styles.title}>Video probe</Text>
        {lines.map((l, i) => (
          <Text key={i} style={styles.line}>
            {l}
          </Text>
        ))}
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  root: {flex: 1, backgroundColor: '#000'},
  surface: {position: 'absolute', top: 0, left: 0, right: 0, bottom: 0},
  overlay: {position: 'absolute', top: 20, left: 24, right: 24},
  title: {color: '#fff', fontSize: 26, fontWeight: '600', marginBottom: 6},
  line: {color: '#3ddc97', fontSize: 17, marginTop: 2},
});
