#!/usr/bin/env python3
"""
Stage 1b (film) — find where people are SPEAKING, and treat everything else as
available.

The first version of this looked for silence, and on real footage that is the
wrong question. A 52-second film trailer contains about 2.5 seconds of silence,
all of it at the very start and end — the middle is continuous score. Silence
detection said there was nowhere to put a description, which is plainly false:
human describers talk over music and effects all the time. What they do not do
is talk over dialogue.

So: transcribe the audio, take the word timings as the speech intervals, and
the gaps are what is left. Music is not an obstacle.

Uses Amazon Transcribe, which needs the audio in S3.
"""
import argparse, json, os, subprocess, sys, tempfile, time, uuid

_CA = os.environ.get("SIGHTLINE_CA_BUNDLE", os.path.expanduser("~/.config/sightline-ca.pem"))
if os.path.exists(_CA):
    for _v in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "AWS_CA_BUNDLE"):
        os.environ[_v] = _CA
if os.environ.get("SIGHTLINE_AWS_PROFILE"):
    os.environ["AWS_PROFILE"] = os.environ["SIGHTLINE_AWS_PROFILE"]

REGION = os.environ.get("AWS_REGION", "us-west-2")
MIN_GAP_S = 0.8
# Asymmetric on purpose, and the asymmetry is the point.
#
# These were both 0.15 s, which meant a description began a seventh of a
# second after the last word of dialogue. A blind reviewer watched the trailer
# three times and only on the third did he notice the narrator say "hunter" --
# a line that ends at 38.91 s, with our voice starting at 39.06 s. He had no
# time to take in what he had just heard before another voice arrived.
#
# The pause after someone speaks is when the listener understands them, so it
# is worth far more than the words it costs. The pause before the next line is
# only there to avoid collision, so it can stay short.
AFTER_SPEECH_S = 0.7
BEFORE_SPEECH_S = 0.35
# Words closer together than this belong to the same run of speech.
JOIN_WORDS_S = 0.35


def _bucket():
    b = os.environ.get("SIGHTLINE_BUCKET")
    if b:
        return b
    p = os.path.expanduser("~/.config/sightline-bucket")
    if os.path.exists(p):
        return open(p).read().strip()
    sys.exit("no bucket: set SIGHTLINE_BUCKET or write ~/.config/sightline-bucket")


def duration(path):
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip())


def transcribe(media, cache=None):
    """Return the raw Transcribe result, caching it next to the media."""
    if cache and os.path.exists(cache):
        return json.load(open(cache))

    import boto3
    s3 = boto3.client("s3", region_name=REGION)
    tr = boto3.client("transcribe", region_name=REGION)
    bucket = _bucket()

    with tempfile.TemporaryDirectory() as td:
        audio = os.path.join(td, "audio.mp3")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", media,
                        "-vn", "-c:a", "libmp3lame", "-b:a", "96k", audio], check=True)
        key = f"transcribe-input/{uuid.uuid4().hex}.mp3"
        s3.upload_file(audio, bucket, key)

    job = f"sightline-{uuid.uuid4().hex[:12]}"
    tr.start_transcription_job(
        TranscriptionJobName=job,
        Media={"MediaFileUri": f"s3://{bucket}/{key}"},
        MediaFormat="mp3",
        LanguageCode="en-US",
    )
    print(f"  transcription job {job} started", file=sys.stderr)
    while True:
        st = tr.get_transcription_job(TranscriptionJobName=job)["TranscriptionJob"]
        status = st["TranscriptionJobStatus"]
        if status in ("COMPLETED", "FAILED"):
            break
        time.sleep(1.5)
    if status == "FAILED":
        sys.exit(f"transcription failed: {st.get('FailureReason')}")

    import urllib.request
    url = st["Transcript"]["TranscriptFileUri"]
    with urllib.request.urlopen(url) as r:
        result = json.loads(r.read())
    s3.delete_object(Bucket=bucket, Key=key)
    if cache:
        json.dump(result, open(cache, "w"))
    return result


def speech_intervals(result):
    """Merge word timings into runs of speech."""
    runs = []
    for item in result["results"]["items"]:
        if item["type"] != "pronunciation":
            continue
        s, e = float(item["start_time"]), float(item["end_time"])
        if runs and s - runs[-1][1] <= JOIN_WORDS_S:
            runs[-1][1] = e
        else:
            runs.append([s, e])
    return [tuple(r) for r in runs]


def gaps_from_speech(runs, total, min_gap=MIN_GAP_S,
                     after=AFTER_SPEECH_S, before=BEFORE_SPEECH_S):
    gaps, cursor = [], 0.0
    for s, e in runs + [(total, total)]:
        # Leave room after the previous line to land, and before the next to
        # begin. The first gap starts at 0, where there is nothing to land.
        lo = cursor + (after if cursor > 0 else 0.0)
        hi = s - before
        if hi - lo >= min_gap:
            gaps.append({"start": round(lo, 3), "end": round(hi, 3),
                         "len_s": round(hi - lo, 3)})
        cursor = max(cursor, e)
    return gaps


def main():
    p = argparse.ArgumentParser()
    p.add_argument("media")
    p.add_argument("--min-gap", type=float, default=MIN_GAP_S)
    p.add_argument("--cache", help="cache the transcript here")
    p.add_argument("--out", required=True)
    a = p.parse_args()

    total = duration(a.media)
    result = transcribe(a.media, a.cache)
    runs = speech_intervals(result)
    gaps = gaps_from_speech(runs, total, a.min_gap)

    text = result["results"]["transcripts"][0]["transcript"]
    spoken = sum(e - s for s, e in runs)
    print(f"  transcript: {text[:110]}{'...' if len(text) > 110 else ''}", file=sys.stderr)
    print(f"  {len(runs)} speech runs, {spoken:.1f}s of {total:.1f}s is dialogue",
          file=sys.stderr)
    print(f"  {len(gaps)} gaps, {sum(g['len_s'] for g in gaps):.1f}s usable",
          file=sys.stderr)

    json.dump({"media": a.media, "duration_s": round(total, 3),
               "method": "speech (Amazon Transcribe)",
               "speech_runs": [{"start": round(s, 3), "end": round(e, 3)} for s, e in runs],
               "count": len(gaps), "gaps": gaps},
              open(a.out, "w"), indent=2)
    print(f"{len(gaps)} gaps -> {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
