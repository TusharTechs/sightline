#!/usr/bin/env python3
"""
Everything the hosted question endpoint needs, as static files.

Answering a question about a moment needs three things: the frame the viewer
is on, the dialogue spoken up to then, and the descriptions they have heard.
On a local machine the server pulls the frame out of the video with ffmpeg. A
serverless endpoint cannot: it would have to download the whole film for every
question.

So the frames are extracted once, one per second, small, and published beside
the video. The endpoint fetches a single 11 KB JPEG instead of a 12 MB film,
and the whole thing stays static hosting plus one function.

    build_ask_assets.py VIDEO_DIR --transcript t.json [--fps 1] [--width 400]
"""
import argparse, json, os, subprocess, sys


def extract(video, out_dir, fps, width, quality=5):
    os.makedirs(out_dir, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", video,
         "-vf", f"fps={fps},scale={width}:-2", "-q:v", str(quality),
         os.path.join(out_dir, "%05d.jpg")], check=True)
    return sorted(os.listdir(out_dir))


def shift_transcript(src, dst, start=0.0, end=None):
    """Slice a transcript to a segment and rebase its timings to it.

    The film clip is cut out of the middle of a longer file, so the cached
    transcript's timings are wrong for it by exactly the offset.
    """
    r = json.load(open(src))
    items = r["results"]["items"]
    out = []
    for it in items:
        if it.get("type") != "pronunciation":
            out.append(it)
            continue
        s0, e0 = float(it["start_time"]), float(it["end_time"])
        if s0 < start or (end is not None and e0 > end):
            continue
        it = dict(it)
        it["start_time"] = f"{s0 - start:.2f}"
        it["end_time"] = f"{e0 - start:.2f}"
        out.append(it)
    r["results"]["items"] = out
    json.dump(r, open(dst, "w"))
    return sum(1 for i in out if i.get("type") == "pronunciation")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("video_dir", help="a published directory holding content.mp4")
    p.add_argument("--transcript", required=True)
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--end", type=float)
    p.add_argument("--fps", type=float, default=1.0)
    p.add_argument("--width", type=int, default=400)
    a = p.parse_args()

    video = os.path.join(a.video_dir, "content.mp4")
    frames = extract(video, os.path.join(a.video_dir, "frames"), a.fps, a.width)
    words = shift_transcript(a.transcript,
                             os.path.join(a.video_dir, "transcript.json"),
                             a.start, a.end)
    size = sum(os.path.getsize(os.path.join(a.video_dir, "frames", f))
               for f in frames) / 1048576
    print(f"  {a.video_dir}: {len(frames)} frames ({size:.1f} MB), "
          f"{words} transcript words")


if __name__ == "__main__":
    main()
