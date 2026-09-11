/**
 * Video playback over MSE.
 *
 * URL mode (`player.src = url`) does not work on this platform — it fails
 * before issuing a network request, for every media type. MSE does, because we
 * fetch the bytes ourselves and hand them to the player. See probes/ and
 * HANDOFF.md.
 *
 * Content must be FRAGMENTED mp4; a plain mp4 will not append.
 */
import {
  VideoPlayer,
  MediaSource,
} from '@amazon-devices/react-native-w3cmedia';

export class MsePlayer {
  private player: VideoPlayer | null = null;
  private ms: MediaSource | null = null;
  private surface: string | null = null;
  private ready = false;

  async initialize(): Promise<void> {
    this.player = new VideoPlayer();
    await this.player.initialize();
    this.ready = true;
    if (this.surface) {
      this.player.setSurfaceHandle(this.surface);
    }
  }

  /** Surface arrives from a React callback and may precede initialize(). */
  attachSurface(handle: string): void {
    this.surface = handle;
    if (this.ready && this.player) {
      this.player.setSurfaceHandle(handle);
    }
  }

  detachSurface(handle: string): void {
    this.surface = null;
    try {
      this.player?.clearSurfaceHandle(handle);
    } catch {}
  }

  on(event: string, fn: () => void): void {
    this.player?.addEventListener(event as any, fn);
  }

  /** Fetch a fragmented mp4 and feed it through a SourceBuffer. */
  async load(url: string, mimeCodec: string): Promise<void> {
    const player = this.player;
    if (!player) {
      throw new Error('load() before initialize()');
    }
    const ms = new MediaSource();
    this.ms = ms;

    const opened = new Promise<void>((resolve) => {
      let done = false;
      const go = () => {
        if (!done) {
          done = true;
          resolve();
        }
      };
      try {
        (ms as any).addEventListener?.('sourceopen', go);
      } catch {}
      // Some builds open synchronously; don't hang waiting for the event.
      setTimeout(() => {
        if (String((ms as any).readyState).toLowerCase().includes('open')) {
          go();
        }
      }, 500);
    });

    (player as any).srcObject = ms;
    await opened;

    const sb = ms.addSourceBuffer(mimeCodec);
    const res = await fetch(url);
    const bytes = new Uint8Array(await res.arrayBuffer());

    await new Promise<void>((resolve) => {
      sb.addEventListener('updateend', () => {
        try {
          ms.endOfStream();
        } catch {}
        resolve();
      });
      sb.appendBuffer(bytes);
    });
  }

  play(): void {
    this.player?.play?.();
  }

  pause(): void {
    this.player?.pause?.();
  }

  get paused(): boolean {
    return Boolean((this.player as any)?.paused);
  }

  get currentTime(): number {
    return Number((this.player as any)?.currentTime ?? 0);
  }

  get duration(): number {
    return Number((this.player as any)?.duration ?? 0);
  }

  /** Playback rate. Description budgets are computed against this host-side. */
  setRate(rate: number): void {
    try {
      (this.player as any).playbackRate = rate;
    } catch {}
  }

  get rate(): number {
    return Number((this.player as any)?.playbackRate ?? 1);
  }

  async destroy(): Promise<void> {
    try {
      await this.player?.deinitialize();
    } catch {}
    this.player = null;
    this.ms = null;
    this.ready = false;
  }
}
