/**
 * The app speaking for itself.
 *
 * Sightline's users cannot see the HUD, so every control has to confirm itself
 * aloud. This does not go through the platform screen reader: VoiceView cannot
 * be enabled on the virtual device at all (FRICTION-LOG FL-011), and on real
 * hardware it may simply be off. An accessibility app that only works when
 * another accessibility feature is already switched on is not much use.
 *
 * Phrases are pre-rendered PCM shipped with the bundle, so a confirmation never
 * waits on the network or on a speech engine.
 *
 * Interface speech ALWAYS interrupts description. The user just pressed a
 * button — telling them what happened matters more than finishing a sentence
 * about the film.
 */
import {DescriptionChannel} from './DescriptionChannel';

export type Phrase =
  | 'ready' | 'hint' | 'playing' | 'paused'
  | 'rate_1' | 'rate_15' | 'rate_2'
  | 'mode_fit' | 'mode_pause'
  | 'target_tv' | 'target_phone'
  | 'ended' | 'error' | 'help';

interface Entry {
  pcm: string;
  text: string;
  duration: number;
}

export class UiVoice {
  private buffers = new Map<Phrase, ArrayBuffer>();
  private manifest: Record<string, Entry> = {};
  private ready = false;

  constructor(private host: string, private channel: DescriptionChannel) {}

  async load(): Promise<void> {
    const res = await fetch(`${this.host}/ui-voice.json`);
    this.manifest = await res.json();
    await Promise.all(
      Object.entries(this.manifest).map(async ([key, e]) => {
        const buf = await (await fetch(`${this.host}/${e.pcm}`)).arrayBuffer();
        this.buffers.set(key as Phrase, buf);
      }),
    );
    this.ready = true;
  }

  text(p: Phrase): string {
    return this.manifest[p]?.text ?? '';
  }

  /** Speak a confirmation, cutting off whatever was being said. */
  async say(p: Phrase): Promise<void> {
    if (!this.ready) {
      return;
    }
    const buf = this.buffers.get(p);
    if (!buf) {
      return;
    }
    this.channel.cancel();
    // Let the in-flight write unwind before taking the stream.
    await new Promise((r) => setTimeout(r, 30));
    await this.channel.speak(buf);
  }
}
