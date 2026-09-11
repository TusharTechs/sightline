#!/usr/bin/env python3
"""
Stage 4 — speech, and the word budget that constrains stage 3.

Emits 16-bit 48 kHz stereo interleaved PCM, which is what
AudioPlaybackStream.writeAsync() takes on Vega (see HANDOFF.md). Never MP3:
the device path is raw PCM and all decoding happens here.

The budget function is the important part. the ADP list's constraint is that a
description which fits a gap at 1x lands on top of the narrator at 2x, and that
the fix is fewer words rather than faster speech. So the budget is computed in
PLAYBACK time, and speech is always rendered at a comfortable rate.
"""
import argparse, json, os, re, subprocess, sys, tempfile

RATE_HZ = 48000
CHANNELS = 2
BYTES_PER_FRAME = CHANNELS * 2   # s16

# Comfortable description rate. Deliberately NOT raised to fit more in — the
# whole point is that speeding up speech over sped-up content is unintelligible.
DEFAULT_WPM = 170
DEFAULT_VOICE = "Samantha"


def budget_words(gap_seconds: float, playback_rate: float, wpm: int = DEFAULT_WPM) -> int:
    """How many words fit in a gap, measured in playback time.

    A 3s gap at 2x is 1.5s of wall clock. We say fewer words at a normal rate,
    we do not say the same words twice as fast.
    """
    wall_clock = gap_seconds / max(playback_rate, 0.01)
    return max(0, int(wall_clock * (wpm / 60.0)))


def synthesize(text: str, out_pcm: str, wpm: int = DEFAULT_WPM, voice: str = DEFAULT_VOICE):
    with tempfile.TemporaryDirectory() as td:
        aiff = os.path.join(td, "s.aiff")
        subprocess.run(["say", "-v", voice, "-r", str(wpm), "-o", aiff, text], check=True)
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", aiff,
            "-ar", str(RATE_HZ), "-ac", str(CHANNELS),
            "-f", "s16le", "-acodec", "pcm_s16le", out_pcm,
        ], check=True)
    n = os.path.getsize(out_pcm)
    return {
        "path": out_pcm,
        "bytes": n,
        "duration_s": round(n / (RATE_HZ * BYTES_PER_FRAME), 3),
        "words": len(re.findall(r"\S+", text)),
        "wpm": wpm,
        "voice": voice,
        "format": f"s16le {RATE_HZ}Hz {CHANNELS}ch interleaved",
    }


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("say", help="synthesize text to PCM")
    s.add_argument("text")
    s.add_argument("--out", required=True)
    s.add_argument("--wpm", type=int, default=DEFAULT_WPM)
    s.add_argument("--voice", default=DEFAULT_VOICE)

    b = sub.add_parser("budget", help="words that fit a gap at a playback rate")
    b.add_argument("--gap", type=float, required=True)
    b.add_argument("--rate", type=float, default=1.0)
    b.add_argument("--wpm", type=int, default=DEFAULT_WPM)

    a = p.parse_args()
    if a.cmd == "say":
        print(json.dumps(synthesize(a.text, a.out, a.wpm, a.voice), indent=2))
    else:
        print(json.dumps({
            "gap_media_s": a.gap, "playback_rate": a.rate,
            "gap_wall_clock_s": round(a.gap / a.rate, 3),
            "wpm": a.wpm, "words_that_fit": budget_words(a.gap, a.rate, a.wpm),
        }, indent=2))


if __name__ == "__main__":
    main()
