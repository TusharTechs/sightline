#!/usr/bin/env python3
"""
Stage 6 — render the described output.

Two modes, per the ADP list. They are genuinely different behaviours, not a
verbosity setting:

  pause   Freeze the picture and speak. Correct for training and walkthroughs,
          where the narration never stops and there is nowhere to fit anything.
          Plain and complete beats beautiful.
  fit     Never pause; the description must fit a gap. Correct for film.
          (Gap detection is not implemented yet — needs a real soundtrack.)

Output is a normal mp4 so a blind tester can play it anywhere. The device path
uses raw PCM via AudioPlaybackStream instead; this renderer is for review.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from speech import synthesize, RATE_HZ

W, H, FPS = 1280, 720, 8
VENC = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-r", str(FPS)]
AENC = ["-c:a", "aac", "-ar", "48000", "-ac", "2"]


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ffmpeg failed:\n  {' '.join(cmd[:9])}...\n{r.stderr[-900:]}")


def seg_video(src, a, b, out):
    """A stretch of the original, with silent audio."""
    run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{a:.3f}", "-to", f"{b:.3f}",
         "-i", src, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
         "-shortest", *VENC, *AENC, out])


def seg_freeze(src, t, wav, dur, out):
    """A held frame with the description spoken over it."""
    still = out + ".png"
    run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", src,
         "-frames:v", "1", still])
    run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", still, "-i", wav,
         "-t", f"{dur:.3f}", *VENC, *AENC, out])
    os.unlink(still)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("video")
    p.add_argument("events_json", help='[{"t":2.0,"description":"..."}]')
    p.add_argument("--mode", choices=["pause", "fit"], default="pause")
    p.add_argument("--out", required=True)
    p.add_argument("--wpm", type=int, default=170)
    p.add_argument("--lead", type=float, default=0.25,
                   help="seconds of held frame before speech starts")
    a = p.parse_args()

    if a.mode == "fit":
        sys.exit("fit-the-gaps mode needs gap detection on a real soundtrack — not yet built")

    events = json.load(open(a.events_json))
    events = sorted([e for e in events if e.get("description")], key=lambda e: e["t"])
    if not events:
        sys.exit("no events with a description")

    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", a.video], capture_output=True, text=True).stdout.strip())

    tmp = tempfile.mkdtemp()
    parts, manifest, cursor, out_t = [], [], 0.0, 0.0
    try:
        for i, e in enumerate(events):
            t = min(float(e["t"]), dur)
            if t > cursor + 0.01:
                v = os.path.join(tmp, f"v{i:03d}.mp4")
                seg_video(a.video, cursor, t, v)
                parts.append(v)
                out_t += t - cursor
                cursor = t

            pcm = os.path.join(tmp, f"s{i:03d}.pcm")
            meta = synthesize(e["description"], pcm, wpm=a.wpm)
            wav = os.path.join(tmp, f"s{i:03d}.wav")
            run(["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", str(RATE_HZ),
                 "-ac", "2", "-i", pcm, wav])

            hold = meta["duration_s"] + a.lead
            f = os.path.join(tmp, f"f{i:03d}.mp4")
            seg_freeze(a.video, t, wav, hold, f)
            parts.append(f)
            manifest.append({
                "source_t": round(t, 3), "output_t": round(out_t, 3),
                "held_for_s": round(hold, 3), "words": meta["words"],
                "speech_s": meta["duration_s"], "description": e["description"],
            })
            out_t += hold

        if cursor < dur - 0.01:
            v = os.path.join(tmp, "vtail.mp4")
            seg_video(a.video, cursor, dur, v)
            parts.append(v)
            out_t += dur - cursor

        lst = os.path.join(tmp, "concat.txt")
        open(lst, "w").write("".join(f"file '{p}'\n" for p in parts))
        run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", lst, "-c", "copy", a.out])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    side = os.path.splitext(a.out)[0] + ".timeline.json"
    json.dump({"mode": a.mode, "source_duration_s": round(dur, 3),
               "output_duration_s": round(out_t, 3), "descriptions": manifest},
              open(side, "w"), indent=2)
    print(f"{a.out}  ({dur:.1f}s source -> {out_t:.1f}s described, "
          f"{len(manifest)} descriptions)\n{side}")


if __name__ == "__main__":
    main()
