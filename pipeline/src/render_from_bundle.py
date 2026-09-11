#!/usr/bin/env python3
"""
Render a device bundle to a plain mp4, for review.

The device plays the bundle directly. Blind testers cannot install a Fire TV
app, so this produces the same result as an ordinary video file they can play
anywhere — same media, same cues, same timings.

Descriptions are mixed in at 1x over the original audio, which is what the
accessibility stream does on device. At a higher rate the source is sped up and
the description is NOT, because that is the whole design: fewer words, not
faster speech.
"""
import argparse, json, os, subprocess, sys, tempfile

RATE_HZ = 48000


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ffmpeg failed:\n{' '.join(cmd[:8])}...\n{r.stderr[-800:]}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("bundle_dir")
    p.add_argument("--rate", type=float, default=1.0)
    p.add_argument("--out", required=True)
    a = p.parse_args()

    tl = json.load(open(os.path.join(a.bundle_dir, "timeline.json")))
    media = os.path.join(a.bundle_dir, tl["media"])
    cues = sorted(tl["cues"], key=lambda c: c["t"])

    tmp = tempfile.mkdtemp()
    base = os.path.join(tmp, "base.mp4")
    if a.rate != 1.0:
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", media, "-filter_complex",
             f"[0:v]setpts=PTS/{a.rate}[v];[0:a]atempo={a.rate}[aa]",
             "-map", "[v]", "-map", "[aa]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-crf", "20", "-c:a", "aac", "-ar", "48000", "-ac", "2", base])
    else:
        base = media

    inputs, filters, placed = ["-i", base], [], []
    for i, c in enumerate(cues):
        pcm = os.path.join(a.bundle_dir, c["pcm"])
        if not os.path.exists(pcm):
            continue
        wav = os.path.join(tmp, f"c{i}.wav")
        run(["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", str(RATE_HZ),
             "-ac", "2", "-i", pcm, wav])
        at = c["t"] / a.rate          # cue times are in media time
        inputs += ["-i", wav]
        n = len(filters) + 1
        ms = int(at * 1000)
        filters.append(f"[{n}]adelay={ms}|{ms},volume=1.6[x{n}]")
        placed.append({"t": c["t"], "spoken_at": round(at, 3),
                       "rank": c["rank"], "text": c["text"]})

    if not filters:
        sys.exit("no cues with audio")

    mix = "".join(f"[x{i+1}]" for i in range(len(filters)))
    # The film is ducked under the description, mirroring what
    # USAGE_ACCESSIBILITY does automatically on the device.
    fc = (";".join(filters)
          + f";[0:a]volume=0.55[bed];[bed]{mix}amix=inputs={len(filters)+1}:"
            f"duration=first:normalize=0[a]")
    run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", fc,
         "-map", "0:v", "-map", "[a]", "-c:v", "copy" if a.rate == 1.0 else "libx264",
         "-c:a", "aac", "-ar", "48000", "-ac", "2", a.out])

    side = os.path.splitext(a.out)[0] + ".cues.json"
    json.dump({"rate": a.rate, "mode": tl["mode"], "cues": placed},
              open(side, "w"), indent=2)
    print(f"{a.out}  rate={a.rate}x  {len(placed)} descriptions")


if __name__ == "__main__":
    main()
