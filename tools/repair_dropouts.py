#!/usr/bin/env python3
"""Fill the short holes the screen capture punched into the audio.

BlackHole stops delivering samples while nothing is playing, and it also drops
short runs in the middle of speech: measured on the generation take, 100ms of
digital silence at 2.7s and again at 5.5s, both inside a spoken word. Keeping
the timestamps (aresample=async=1) keeps picture and sound aligned but leaves
those holes audible as breaks.

A hole shorter than a syllable, with speech either side of it, is a dropout
rather than a pause. Bridge it by crossfading what came just before into what
comes just after. That restores continuity, not content -- nothing is invented
beyond what the two edges already contain -- and it is inaudible next to a
silent gap, which is not.

Anything longer than MAX_GAP is left alone: real pauses between sentences are
supposed to be silent.
"""
import sys, wave, numpy as np

MIN_GAP = 0.015      # shorter than this is a click, not a dropout
MAX_GAP = 0.30       # longer than this is a real pause
FLOOR = 3e-4         # below this counts as digital silence
EDGE = 0.08          # speech must be present within this of both sides

def read(path):
    w = wave.open(path, 'rb')
    sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
    a = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    w.close()
    return a.reshape(-1, ch), sr, ch

def write(path, a, sr, ch):
    w = wave.open(path, 'wb')
    w.setnchannels(ch); w.setsampwidth(2); w.setframerate(sr)
    w.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())
    w.close()

def repair(src, dst):
    a, sr, ch = read(src)
    mono = np.abs(a).max(axis=1)
    quiet = mono < FLOOR
    # run-length over the quiet mask
    edges = np.flatnonzero(np.diff(quiet.astype(np.int8)))
    starts = (edges + 1)[quiet[edges + 1]]
    ends = (edges + 1)[~quiet[edges + 1]]
    if quiet[0]:
        starts = np.r_[0, starts]
    if quiet[-1]:
        ends = np.r_[ends, len(quiet)]
    n_fixed = 0
    e = int(EDGE * sr)
    for s, t in zip(starts, ends):
        g = t - s
        if not (MIN_GAP * sr <= g <= MAX_GAP * sr):
            continue
        if s - e < 0 or t + e > len(a):
            continue
        # speech on both sides, or it is an ordinary silence
        if mono[max(0, s - e):s].max() < FLOOR * 6:
            continue
        if mono[t:t + e].max() < FLOOR * 6:
            continue
        pre = a[s - g:s]
        post = a[t:t + g]
        ramp = np.linspace(0.0, 1.0, g, dtype=np.float32)[:, None]
        a[s:t] = pre * (1 - ramp) + post * ramp
        n_fixed += 1
    write(dst, a, sr, ch)
    return n_fixed

if __name__ == "__main__":
    print(repair(sys.argv[1], sys.argv[2]))
