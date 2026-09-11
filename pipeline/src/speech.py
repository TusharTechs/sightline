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

# Local TLS inspection breaks the AWS SDK without a bundle containing the
# machine's own chain; see tools/make-ca-bundle.sh. Harmless when absent.
_CA = os.environ.get("SIGHTLINE_CA_BUNDLE", os.path.expanduser("~/.config/sightline-ca.pem"))
if os.path.exists(_CA):
    # Set, not setdefault: a narrower bundle already in the environment is the
    # usual cause of connection failures here, and ours is a superset.
    for _v in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "AWS_CA_BUNDLE"):
        os.environ[_v] = _CA
if os.environ.get("SIGHTLINE_AWS_PROFILE"):
    os.environ["AWS_PROFILE"] = os.environ["SIGHTLINE_AWS_PROFILE"]

RATE_HZ = 48000
CHANNELS = 2
BYTES_PER_FRAME = CHANNELS * 2   # s16

# Comfortable description rate. Deliberately NOT raised to fit more in — the
# whole point is that speeding up speech over sped-up content is unintelligible.
#
# MEASURED, not assumed. `python3 src/speech.py calibrate` re-derives it; the
# first value here was a guess of 170 that made every description overflow its
# gap, because the generative voice actually delivers far fewer words a second.
DEFAULT_WPM = 170          # the rate we ASK for (prosody is relative to this)
MEASURED_WPM = float(os.environ.get("SIGHTLINE_MEASURED_WPM", "203"))  # calibrated, Polly generative Joanna
DEFAULT_VOICE = "Samantha"        # macOS `say`
POLLY_VOICE = "Joanna"            # supports the generative engine
POLLY_REGION = os.environ.get("AWS_REGION", "us-east-1")
POLLY_PCM_HZ = 16000              # Polly's pcm output is 16-bit mono, <=16kHz


def budget_words(gap_seconds: float, playback_rate: float, wpm: float = None) -> int:
    """How many words fit in a gap, measured in playback time.

    A 3s gap at 2x is 1.5s of wall clock. We say fewer words at a normal rate,
    we do not say the same words twice as fast.
    """
    wpm = MEASURED_WPM if wpm is None else wpm
    wall_clock = gap_seconds / max(playback_rate, 0.01)
    return max(0, int(wall_clock * (wpm / 60.0)))


def _finish(out_pcm, text, wpm, voice, engine):
    n = os.path.getsize(out_pcm)
    return {
        "path": out_pcm,
        "bytes": n,
        "duration_s": round(n / (RATE_HZ * BYTES_PER_FRAME), 3),
        "words": len(re.findall(r"\S+", text)),
        "wpm": wpm,
        "voice": voice,
        "engine": engine,
        "format": f"s16le {RATE_HZ}Hz {CHANNELS}ch interleaved",
    }


def synthesize_polly(text: str, out_pcm: str, wpm: int = DEFAULT_WPM,
                     voice: str = POLLY_VOICE, engine: str = "generative"):
    """Amazon Polly. Portable (macOS `say` is not) and better quality.

    Polly returns 16-bit mono PCM at up to 16 kHz; ffmpeg resamples to the
    48 kHz stereo the Vega AudioPlaybackStream expects. Rate is set with SSML
    prosody rather than a words-per-minute figure, so `wpm` here only scales
    that — the authoritative length is the measured duration below.
    """
    import boto3
    rate_pct = max(50, min(200, round(100 * wpm / DEFAULT_WPM)))
    ssml = f'<speak><prosody rate="{rate_pct}%">{text}</prosody></speak>'
    polly = boto3.client("polly", region_name=POLLY_REGION)
    try:
        audio = polly.synthesize_speech(
            Text=ssml, TextType="ssml", Engine=engine, VoiceId=voice,
            OutputFormat="pcm", SampleRate=str(POLLY_PCM_HZ))["AudioStream"].read()
    except Exception:
        if engine == "generative":          # not every voice/region has it
            return synthesize_polly(text, out_pcm, wpm, voice, "neural")
        raise
    with tempfile.TemporaryDirectory() as td:
        raw = os.path.join(td, "p.pcm")
        open(raw, "wb").write(audio)
        # Polly pads both ends with silence. In fit-the-gaps mode that padding
        # is charged against the gap budget, so trim it.
        trim = ("silenceremove=start_periods=1:start_silence=0:"
                "start_threshold=-50dB:detection=peak,areverse,"
                "silenceremove=start_periods=1:start_silence=0:"
                "start_threshold=-50dB:detection=peak,areverse")
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "s16le", "-ar", str(POLLY_PCM_HZ), "-ac", "1", "-i", raw,
            "-af", trim, "-ar", str(RATE_HZ), "-ac", str(CHANNELS),
            "-f", "s16le", "-acodec", "pcm_s16le", out_pcm,
        ], check=True)
    return _finish(out_pcm, text, wpm, voice, f"polly:{engine}")


def synthesize_say(text: str, out_pcm: str, wpm: int = DEFAULT_WPM, voice: str = DEFAULT_VOICE):
    with tempfile.TemporaryDirectory() as td:
        aiff = os.path.join(td, "s.aiff")
        subprocess.run(["say", "-v", voice, "-r", str(wpm), "-o", aiff, text], check=True)
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", aiff,
            "-ar", str(RATE_HZ), "-ac", str(CHANNELS),
            "-f", "s16le", "-acodec", "pcm_s16le", out_pcm,
        ], check=True)
    return _finish(out_pcm, text, wpm, voice, "say")


def synthesize(text: str, out_pcm: str, wpm: int = DEFAULT_WPM, voice: str = None,
               engine: str = None):
    """Dispatch to Polly (default, portable) or macOS `say` (offline fallback)."""
    engine = engine or os.environ.get("SIGHTLINE_TTS", "polly")
    if engine == "say":
        return synthesize_say(text, out_pcm, wpm, voice or DEFAULT_VOICE)
    return synthesize_polly(text, out_pcm, wpm, voice or POLLY_VOICE)


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("say", help="synthesize text to PCM")
    s.add_argument("text")
    s.add_argument("--out", required=True)
    s.add_argument("--wpm", type=int, default=DEFAULT_WPM)
    s.add_argument("--voice")
    s.add_argument("--engine", choices=["polly", "say"])

    c = sub.add_parser("calibrate", help="measure the voice's real words per minute")
    c.add_argument("--voice")
    c.add_argument("--engine", choices=["polly", "say"])

    b = sub.add_parser("budget", help="words that fit a gap at a playback rate")
    b.add_argument("--gap", type=float, required=True)
    b.add_argument("--rate", type=float, default=1.0)
    b.add_argument("--wpm", type=int, default=DEFAULT_WPM)

    a = p.parse_args()
    if a.cmd == "calibrate":
        import tempfile as _tf
        samples = [
            "The checkbox is now ticked.",
            "Save changes is now enabled and ready to click.",
            "A confirmation dialog has opened asking you to apply the changes you made.",
        ]
        tot_w = tot_s = 0.0
        with _tf.TemporaryDirectory() as td:
            for i, t in enumerate(samples):
                m = synthesize(t, os.path.join(td, f"c{i}.pcm"), voice=a.voice,
                               engine=a.engine)
                tot_w += m["words"]; tot_s += m["duration_s"]
                print(f"  {m['words']:>2}w  {m['duration_s']:>6}s  "
                      f"{m['words']/m['duration_s']*60:>6.1f} wpm   {t[:44]}")
        print(json.dumps({"measured_wpm": round(tot_w / tot_s * 60, 1),
                          "engine": m["engine"], "voice": m["voice"],
                          "hint": "export SIGHTLINE_MEASURED_WPM=<value>"}, indent=2))
        return

    if a.cmd == "say":
        print(json.dumps(synthesize(a.text, a.out, a.wpm, a.voice, a.engine), indent=2))
    else:
        print(json.dumps({
            "gap_media_s": a.gap, "playback_rate": a.rate,
            "gap_wall_clock_s": round(a.gap / a.rate, 3),
            "wpm": a.wpm, "words_that_fit": budget_words(a.gap, a.rate, a.wpm),
        }, indent=2))


if __name__ == "__main__":
    main()
