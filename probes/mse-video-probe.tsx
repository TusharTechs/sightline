/**
 * MSE mode probe — the last untested playback path.
 *
 * URL mode fails on this device for every media type, before it opens the
 * source and without issuing a network request. MSE is structurally different:
 * JavaScript fetches the bytes and feeds them in through SourceBuffer, so it
 * does not depend on whatever URL handling is broken.
 *
 * Deliberately no Shaka/hls.js. Using MediaSource and SourceBuffer directly
 * keeps the test about the platform rather than about a player library and its
 * Vega patches.
 *
 * Content is fragmented MP4 (+frag_keyframe+empty_moov+default_base_moof),
 * appended in one buffer, which is all MSE needs to reach canplay.
 */
import React, {useCallback, useEffect, useRef, useState} from 'react';
import {View, Text, StyleSheet} from 'react-native';
import {
  VideoPlayer,
  MediaSource,
  KeplerVideoSurfaceView,
} from '@amazon-devices/react-native-w3cmedia';

const HOST = 'http://10.0.2.2:8099';
const CASE = {
  name: 'mse-video-only',
  url: `${HOST}/frag-video.mp4`,
  mime: 'video/mp4; codecs="avc1.64001F"',
};

const beacon = (m: string) => {
  try {
    fetch(`${HOST}/MSE/${encodeURIComponent(m)}`).catch(() => {});
  } catch {}
};

export const App = () => {
  const surface = useRef<string | null>(null);
  const started = useRef(false);
  const [lines, setLines] = useState<string[]>([]);
  const log = useCallback((s: string) => {
    setLines((p) => [...p.slice(-13), s]);
    beacon(s);
  }, []);

  const run = useCallback(async () => {
    const player = new VideoPlayer();
    try {
      await player.initialize();
      log('player initialized');

      (['loadstart', 'loadedmetadata', 'canplay', 'playing'] as const).forEach((e) =>
        player.addEventListener(e, () => log(`player: ${e}`)),
      );
      player.addEventListener('error', () =>
        log(`player ERROR code=${(player as any)?.error?.code ?? '?'}`),
      );

      if (surface.current) {
        player.setSurfaceHandle(surface.current);
        log('surface attached');
      }

      // Does the platform admit to supporting this type at all?
      try {
        const sup = (MediaSource as any)?.isTypeSupported?.(CASE.mime);
        log(`isTypeSupported=${sup}`);
      } catch (e: any) {
        log(`isTypeSupported threw ${e?.message ?? e}`);
      }

      const ms = new MediaSource();
      log(`MediaSource created, readyState=${(ms as any).readyState}`);

      let opened = false;
      const onOpen = async () => {
        if (opened) return;
        opened = true;
        log('sourceopen');
        try {
          const sb = ms.addSourceBuffer(CASE.mime);
          log('addSourceBuffer ok');
          sb.addEventListener('updateend', () => {
            log('updateend');
            try {
              ms.endOfStream();
              log('endOfStream called');
            } catch (e: any) {
              log(`endOfStream threw ${e?.message ?? e}`);
            }
            player.play?.();
          });
          sb.addEventListener('error', () => log('SourceBuffer error'));

          log('fetching segment...');
          const res = await fetch(CASE.url);
          const buf = await res.arrayBuffer();
          log(`fetched ${buf.byteLength} bytes`);
          sb.appendBuffer(new Uint8Array(buf));
          log('appendBuffer called');
        } catch (e: any) {
          log(`sourceopen path threw ${e?.message ?? e}`);
        }
      };

      try {
        (ms as any).addEventListener?.('sourceopen', onOpen);
      } catch {}

      (player as any).srcObject = ms;
      log('srcObject assigned');

      // Some implementations open synchronously; don't wait forever on an event.
      setTimeout(() => {
        const rs = (ms as any).readyState;
        log(`after 1.5s readyState=${rs}`);
        if (!opened && String(rs).toLowerCase().includes('open')) {
          onOpen();
        }
      }, 1500);

      setTimeout(() => log('DONE (12s)'), 12000);
    } catch (e: any) {
      log(`THREW ${e?.message ?? e}`);
    }
  }, [log]);

  const onSurfaceViewCreated = useCallback(
    (h: string) => {
      surface.current = h;
      log('surface created');
      if (!started.current) {
        started.current = true;
        run();
      }
    },
    [log, run],
  );

  useEffect(() => beacon('MSE APP START'), []);

  return (
    <View style={styles.root}>
      <KeplerVideoSurfaceView
        style={styles.surface}
        onSurfaceViewCreated={onSurfaceViewCreated}
        onSurfaceViewDestroyed={() => log('surface destroyed')}
      />
      <View style={styles.overlay}>
        <Text style={styles.title}>MSE probe</Text>
        {lines.map((l, i) => (
          <Text key={i} style={styles.line}>{l}</Text>
        ))}
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  root: {flex: 1, backgroundColor: '#000'},
  surface: {position: 'absolute', top: 0, left: 0, right: 0, bottom: 0},
  overlay: {position: 'absolute', top: 16, left: 20, right: 20},
  title: {color: '#fff', fontSize: 24, fontWeight: '600', marginBottom: 4},
  line: {color: '#3ddc97', fontSize: 16, marginTop: 1},
});
