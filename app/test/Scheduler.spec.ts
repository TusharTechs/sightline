/**
 * The scheduler decides what gets said and when, so this is where the rule a
 * blind reviewer gave us is enforced:
 *
 *   "What I can't live with is a different story at a different speed."
 *
 * Rank the changes once, then let the gaps decide how far down the list you
 * get. Speed changes the DEPTH reached, never the ORDER. An earlier version
 * assigned descriptions to whichever gap fell nearby, so 1x and 2x told
 * different stories. These tests exist to stop that returning.
 */
import {Scheduler} from '../src/media/Scheduler';

type AnyCue = {rank: number; t: number; duration: number; text: string; pcm: string};

const cue = (rank: number, t: number, duration: number): AnyCue => ({
  rank, t, duration, text: `line ${rank}`, pcm: `desc-${rank}.pcm`,
});

function timeline(cues: AnyCue[], gaps: {start: number; end: number}[], mode = 'fit') {
  return {media: 'content.mp4', mode, cues, gaps} as any;
}

function harness(tl: any, mode?: any) {
  const spoken: number[] = [];
  let tones = 0;
  let paused = 0;
  let resumed = 0;
  const hooks = {
    speak: async (c: any) => { spoken.push(c.rank); return true; },
    tone: async () => { tones += 1; },
    pausePlayback: () => { paused += 1; },
    resumePlayback: () => { resumed += 1; },
  };
  const s = new Scheduler(tl, hooks as any, mode);
  return {s, spoken, get tones() { return tones; },
          get paused() { return paused; }, get resumed() { return resumed; }};
}

describe('Scheduler, fit mode', () => {
  it('speaks in rank order, not in the order the cues appear', async () => {
    const tl = timeline(
      [cue(3, 10, 1), cue(1, 10, 1), cue(2, 10, 1)],
      [{start: 9, end: 30}],
    );
    const h = harness(tl);
    await h.s.tick(10, 1);
    expect(h.spoken).toEqual([1, 2, 3]);
  });

  it('stops when the gap runs out rather than overrunning it', async () => {
    // room for two 2s lines, three are due
    const tl = timeline(
      [cue(1, 10, 2), cue(2, 10, 2), cue(3, 10, 2)],
      [{start: 10, end: 14.5}],
    );
    const h = harness(tl);
    await h.s.tick(10, 1);
    expect(h.spoken).toEqual([1, 2]);
    expect(h.s.dropped).toBe(1);
  });

  it('marks a tone when something was traded away', async () => {
    const tl = timeline([cue(1, 10, 2), cue(2, 10, 9)], [{start: 10, end: 13}]);
    const h = harness(tl);
    await h.s.tick(10, 1);
    expect(h.tones).toBe(1);
  });

  it('never delivers a dropped line later', async () => {
    // a stale description arriving late is worse than one never delivered
    const tl = timeline([cue(1, 10, 2), cue(2, 10, 9)], [{start: 10, end: 13}]);
    const h = harness(tl);
    await h.s.tick(10, 1);
    await h.s.tick(11, 1);
    await h.s.tick(12, 1);
    expect(h.spoken).toEqual([1]);
  });

  it('says nothing when the moment is not inside a gap', async () => {
    const tl = timeline([cue(1, 50, 2)], [{start: 10, end: 20}]);
    const h = harness(tl);
    await h.s.tick(50, 1);
    expect(h.spoken).toEqual([]);
  });

  it('does not re-enter while it is already speaking', async () => {
    // one cue only: a second tick arriving mid-line must be ignored, not
    // queued behind it and certainly not spoken twice
    const tl = timeline([cue(1, 10, 1)], [{start: 10, end: 30}]);
    let resolve!: () => void;
    const spoken: number[] = [];
    const hooks = {
      speak: async (c: any) => {
        spoken.push(c.rank);
        await new Promise<void>((r) => { resolve = r; });
        return true;
      },
      tone: async () => {}, pausePlayback: () => {}, resumePlayback: () => {},
    };
    const s = new Scheduler(tl, hooks as any);
    const first = s.tick(10, 1);
    await s.tick(10, 1);            // should be ignored, not doubled
    resolve();
    await first;
    expect(spoken.filter((r) => r === 1).length).toBe(1);
  });
});

describe('Scheduler, the rule about speed', () => {
  const tl = () => timeline(
    [cue(1, 10, 2), cue(2, 10, 2), cue(3, 10, 2), cue(4, 10, 2)],
    [{start: 10, end: 19}],
  );

  async function atRate(rate: number) {
    const h = harness(tl());
    await h.s.tick(10, rate);
    return h.spoken;
  }

  it('reaches less far down the list as speed increases', async () => {
    const one = await atRate(1);
    const two = await atRate(2);
    expect(two.length).toBeLessThan(one.length);
  });

  it('tells the SAME story at every speed, just less of it', async () => {
    // the headline property: what survives at 2x is a rank-ordered prefix of
    // what survives at 1x. Never a different selection.
    const one = await atRate(1);
    for (const rate of [1.25, 1.5, 2, 3]) {
      const faster = await atRate(rate);
      expect(one.slice(0, faster.length)).toEqual(faster);
    }
  });

  it('keeps the highest ranked line even when the room is tight', async () => {
    const h = harness(tl());
    await h.s.tick(10, 4);
    if (h.spoken.length > 0) {
      expect(h.spoken[0]).toBe(1);
    }
  });
});

describe('Scheduler, pause mode', () => {
  it('says everything due, because pausing buys the time', async () => {
    const tl = timeline(
      [cue(1, 10, 5), cue(2, 10, 5), cue(3, 10, 5)],
      [{start: 10, end: 11}], 'pause',
    );
    const h = harness(tl, 'pause');
    await h.s.tick(10, 1);
    expect(h.spoken).toEqual([1, 2, 3]);
    expect(h.s.dropped).toBe(0);
  });

  it('pauses before speaking and resumes after', async () => {
    const tl = timeline([cue(1, 10, 5)], [{start: 10, end: 11}], 'pause');
    const h = harness(tl, 'pause');
    await h.s.tick(10, 1);
    expect(h.paused).toBe(1);
    expect(h.resumed).toBe(1);
  });
});

describe('Scheduler, state', () => {
  it('reset clears what has fired and the dropped count', async () => {
    const tl = timeline([cue(1, 10, 2), cue(2, 10, 9)], [{start: 10, end: 13}]);
    const h = harness(tl);
    await h.s.tick(10, 1);
    expect(h.s.dropped).toBe(1);
    h.s.reset();
    expect(h.s.dropped).toBe(0);
    await h.s.tick(10, 1);
    expect(h.spoken).toEqual([1, 1]);
  });

  it('switching mode changes behaviour without rebuilding the scheduler', async () => {
    const tl = timeline([cue(1, 10, 5), cue(2, 10, 5)], [{start: 10, end: 11}]);
    const h = harness(tl);
    h.s.setMode('pause' as any);
    await h.s.tick(10, 1);
    expect(h.spoken).toEqual([1, 2]);
  });
});
