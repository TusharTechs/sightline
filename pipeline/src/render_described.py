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
from speech import synthesize, budget_words, RATE_HZ

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


def render_fit(a, events):
    """Fit-the-gaps: never pause, place each description in a silence.

    The clip is rendered AT the requested playback rate, and the description
    audio is laid in unmodified at 1x. That is the whole point — at 2x a 2.6s
    media gap is 1.3s of wall clock, and the description has to be short enough
    to fit that, not merely time-compressed to fit it. Speeding the speech up
    with the film makes it fit arithmetically and unintelligible in practice.
    """
    gaps = json.load(open(a.gaps))["gaps"]
    rate = a.rate
    tmp = tempfile.mkdtemp()
    placed, dropped = [], []
    try:
        # source, sped up; description audio is NOT sped up
        base = os.path.join(tmp, "base.mp4")
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", a.video,
             "-filter_complex",
             f"[0:v]setpts=PTS/{rate}[v];[0:a]atempo={rate}[aa]",
             "-map", "[v]", "-map", "[aa]", *VENC, *AENC, base])

        used, inputs, filters = set(), ["-i", base], []
        for i, e in enumerate(events):
            t = float(e["t"])
            # Assignment is decided in fit_descriptions.py and carried here, so
            # the two stages cannot disagree about which silence a line belongs
            # in. Fall back to first-fit only for hand-written inputs.
            if "gap_index" in e:
                gi = e["gap_index"]
                gap = gaps[gi] if 0 <= gi < len(gaps) else None
            else:
                gap = next((g for j, g in enumerate(gaps)
                            if j not in used and g["end"] > t), None)
                gi = gaps.index(gap) if gap else None
            if gap is None:
                dropped.append({**e, "why": "no gap at or after this moment"})
                continue
            avail_wall = gap["len_s"] / rate
            budget = budget_words(gap["len_s"], rate)

            pcm = os.path.join(tmp, f"d{i}.pcm")
            meta = synthesize(e["description"], pcm)
            if meta["duration_s"] > avail_wall:
                dropped.append({**e, "why": f"needs {meta['duration_s']}s, "
                                f"gap gives {round(avail_wall,3)}s at {rate}x",
                                "word_budget": budget,
                                "words": meta["words"]})
                continue
            used.add(gi)
            wav = os.path.join(tmp, f"d{i}.wav")
            run(["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le",
                 "-ar", str(RATE_HZ), "-ac", "2", "-i", pcm, wav])
            at_wall = gap["start"] / rate
            inputs += ["-i", wav]
            n = len(filters) + 1
            filters.append(f"[{n}]adelay={int(at_wall*1000)}|{int(at_wall*1000)}[x{n}]")
            placed.append({"source_t": round(t, 3), "spoken_at_s": round(at_wall, 3),
                           "gap_media_s": gap["len_s"],
                           "gap_wall_s": round(avail_wall, 3),
                           "word_budget": budget, "words": meta["words"],
                           "speech_s": meta["duration_s"],
                           "description": e["description"]})

        if filters:
            mix = "".join(f"[x{i+1}]" for i in range(len(filters)))
            fc = ";".join(filters) + f";[0:a]{mix}amix=inputs={len(filters)+1}:" \
                 f"duration=first:normalize=0[a]"
            run(["ffmpeg", "-y", "-loglevel", "error", *inputs,
                 "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
                 "-c:v", "copy", *AENC, a.out])
        else:
            run(["ffmpeg", "-y", "-loglevel", "error", "-i", base, "-c", "copy", a.out])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    side = os.path.splitext(a.out)[0] + ".timeline.json"
    json.dump({"mode": "fit", "playback_rate": rate,
               "placed": placed, "dropped": dropped}, open(side, "w"), indent=2)
    print(f"{a.out}  rate={rate}x  placed={len(placed)}  dropped={len(dropped)}")
    for d in dropped:
        print(f"   DROPPED t={d['t']}  {d['why']}")
    return


def main():
    p = argparse.ArgumentParser()
    p.add_argument("video")
    p.add_argument("events_json", help='[{"t":2.0,"description":"..."}]')
    p.add_argument("--mode", choices=["pause", "fit"], default="pause")
    p.add_argument("--out", required=True)
    p.add_argument("--wpm", type=int, default=170)
    p.add_argument("--lead", type=float, default=0.25,
                   help="pause mode: seconds of held frame before speech starts")
    p.add_argument("--gaps", help="fit mode: detect_gaps.py output")
    p.add_argument("--rate", type=float, default=1.0,
                   help="fit mode: playback rate to render and budget for")
    a = p.parse_args()

    events = json.load(open(a.events_json))
    events = sorted([e for e in events if e.get("description")], key=lambda e: e["t"])
    if not events:
        sys.exit("no events with a description")

    if a.mode == "fit":
        if not a.gaps:
            sys.exit("fit mode needs --gaps (run src/detect_gaps.py first)")
        return render_fit(a, events)

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
