/**
 * The "there was more" tone.
 *
 * Marks descriptions that could not be delivered. Deliberately not speech —
 * words are the scarce resource in a gap, and spending them to say that words
 * were missing is the worst possible trade.
 *
 * Short, soft, and clearly not part of the programme: a brief two-tone fall
 * with a raised-cosine envelope so it has no click at either end.
 */
const RATE = 48000;

export function dropTone(): ArrayBuffer {
  const ms = 140;
  const frames = Math.floor((RATE * ms) / 1000);
  const buf = new ArrayBuffer(frames * 4); // stereo, 16-bit
  const view = new DataView(buf);
  for (let i = 0; i < frames; i++) {
    const p = i / frames;
    // 1200Hz falling to 820Hz — distinct from speech, easy to learn, easy to ignore
    const freq = 1200 - 380 * p;
    // raised cosine in and out, so no click
    const env = 0.5 - 0.5 * Math.cos(2 * Math.PI * Math.min(p, 1));
    const s = Math.sin(2 * Math.PI * freq * (i / RATE)) * env * 0.22 * 32767;
    const v = Math.max(-32768, Math.min(32767, Math.round(s)));
    view.setInt16(i * 4, v, true);
    view.setInt16(i * 4 + 2, v, true);
  }
  return buf;
}
