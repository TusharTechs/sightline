#!/usr/bin/env python3
"""
Build the web version of a bundle.

The device wants raw PCM and a high-bitrate master; a browser wants neither. A
device bundle is about 36 MB per view, of which 21 MB is uncompressed audio —
fine over a LAN, bad for a blind tester on mobile data who is doing us a favour
and is waiting to hear anything at all.

Same timeline, same cues, same page. Smaller files:

    audio   PCM  ->  mp3 64k mono     ~4% of the original
    video   1080p master -> 720p CRF 26, faststart
    result  ~36 MB per view -> ~6 MB

Load time is the reason, not hosting cost — cost at this scale is rounding.
"""
import argparse, glob, json, os, shutil, subprocess, sys

AUDIO_BITRATE = "64k"
VIDEO_HEIGHT = 720
VIDEO_CRF = "26"


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ffmpeg failed: {' '.join(cmd[:8])}...\n{r.stderr[-600:]}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("bundle", help="device bundle directory")
    p.add_argument("--out", required=True, help="web bundle directory")
    a = p.parse_args()

    os.makedirs(a.out, exist_ok=True)
    tl = json.load(open(os.path.join(a.bundle, "timeline.json")))

    # Video: 720p is ample for a description demo and a third of the bytes.
    src = os.path.join(a.bundle, tl["media"])
    dst = os.path.join(a.out, tl["media"])
    run(["ffmpeg", "-y", "-nostdin", "-v", "error", "-i", src,
         "-vf", f"scale=-2:{VIDEO_HEIGHT}", "-c:v", "libx264", "-crf", VIDEO_CRF,
         "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
         "-movflags", "+faststart", dst])

    # Audio: mp3 for every cue and every interface phrase. The page already
    # requests .wav; it now gets .mp3 instead, so the manifest records both.
    converted = 0
    for pcm in sorted(glob.glob(os.path.join(a.bundle, "*.pcm"))):
        name = os.path.basename(pcm)[:-4]
        run(["ffmpeg", "-y", "-nostdin", "-v", "error", "-f", "s16le",
             "-ar", "48000", "-ac", "2", "-i", pcm,
             "-c:a", "libmp3lame", "-b:a", AUDIO_BITRATE, "-ac", "1",
             os.path.join(a.out, name + ".mp3")])
        converted += 1

    for extra in ("timeline.json", "ui-voice.json"):
        s = os.path.join(a.bundle, extra)
        if os.path.exists(s):
            shutil.copy(s, a.out)

    # The page is served from the same place, so it ships with the bundle.
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    page = os.path.join(here, "..", "companion", "phone.html")
    if os.path.exists(page):
        shutil.copy(page, os.path.join(a.out, "index.html"))

    before = sum(os.path.getsize(f) for f in glob.glob(os.path.join(a.bundle, "*"))
                 if os.path.isfile(f))
    after = sum(os.path.getsize(f) for f in glob.glob(os.path.join(a.out, "*"))
                if os.path.isfile(f))
    print(f"  video   -> {VIDEO_HEIGHT}p", file=sys.stderr)
    print(f"  audio   -> {converted} files as mp3 {AUDIO_BITRATE}", file=sys.stderr)
    print(f"  bundle  {before/1e6:.1f} MB -> {after/1e6:.1f} MB "
          f"({after/before*100:.0f}%)", file=sys.stderr)
    print(f"\n{a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
