/**
 * Decides what gets said, and when.
 *
 * The rule this implements, from a blind accessibility professional on the ACB
 * ADP list: rank the changes once, then let the gaps decide how far down the
 * list you get. Speed changes the DEPTH reached, never the ORDER.
 *
 *   "What I can't live with is a different story at a different speed."
 *
 * The previous implementation assigned descriptions to whichever gap happened
 * to fall nearby, so at 1x you heard about one change and at 2x about a
 * different one. That is the defect this class exists to prevent.
 *
 * Anything that does not fit is signalled with a short tone rather than words,
 * because words are the scarce resource:
 *
 *   "It costs you a fraction of a second, it tells me there was more, and I can
 *    go back for it if I care."
 */
import {Cue, Mode, Timeline} from '../types';

export interface SchedulerHooks {
  /** Speak a line. Resolves true if it completed. */
  speak: (cue: Cue) => Promise<boolean>;
  /** Short non-speech tone marking one or more dropped cues. */
  tone: () => Promise<void>;
  pausePlayback: () => void;
  resumePlayback: () => void;
  onCue?: (cue: Cue | null, dropped: number) => void;
}

export class Scheduler {
  private fired = new Set<number>();
  private busy = false;
  private droppedCount = 0;

  constructor(
    private timeline: Timeline,
    private hooks: SchedulerHooks,
    private mode: Mode = timeline.mode,
  ) {}

  get dropped(): number {
    return this.droppedCount;
  }

  setMode(mode: Mode): void {
    this.mode = mode;
  }

  reset(): void {
    this.fired.clear();
    this.droppedCount = 0;
  }

  /** Call on every timeupdate. `rate` is the current playback rate. */
  async tick(currentTime: number, rate: number): Promise<void> {
    if (this.busy) {
      return;
    }
    const due = this.timeline.cues
      .filter((c) => !this.fired.has(c.rank) && c.t <= currentTime)
      .sort((a, b) => a.rank - b.rank);
    if (due.length === 0) {
      return;
    }

    this.busy = true;
    try {
      if (this.mode === 'pause') {
        // Pausing is allowed, so everything due gets said, in rank order.
        this.hooks.pausePlayback();
        for (const cue of due) {
          this.fired.add(cue.rank);
          this.hooks.onCue?.(cue, this.droppedCount);
          await this.hooks.speak(cue);
        }
        this.hooks.onCue?.(null, this.droppedCount);
        this.hooks.resumePlayback();
        return;
      }

      // fit mode: never pause. Work down the ranked list, fitting what we can
      // into the gap this moment falls in.
      const gap = this.timeline.gaps.find(
        (g) => currentTime >= g.start - 0.25 && currentTime < g.end,
      );
      const availableWall = gap ? (gap.end - Math.max(currentTime, gap.start)) / rate : 0;

      let spent = 0;
      let saidAnything = false;
      let skipped = 0;

      for (const cue of due) {
        if (gap && spent + cue.duration <= availableWall) {
          this.fired.add(cue.rank);
          this.hooks.onCue?.(cue, this.droppedCount);
          const ok = await this.hooks.speak(cue);
          if (ok) {
            spent += cue.duration;
            saidAnything = true;
          }
        } else {
          // Doesn't fit. Mark it done — a stale description delivered late is
          // worse than one that was never delivered.
          this.fired.add(cue.rank);
          skipped++;
        }
      }

      if (skipped > 0) {
        this.droppedCount += skipped;
        // Tell the listener something was traded, without spending words.
        if (saidAnything || gap) {
          await this.hooks.tone();
        }
      }
      this.hooks.onCue?.(null, this.droppedCount);
    } finally {
      this.busy = false;
    }
  }
}
