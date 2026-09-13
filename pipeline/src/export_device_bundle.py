#!/usr/bin/env python3
"""
Stage 7 — build the bundle the Fire TV app consumes.

Produces, into one directory:
  <media>.mp4    fragmented, because MSE will not append a plain mp4
  desc-N.pcm     one per cue, 16-bit 48kHz stereo — the device is handed samples
  timeline.json  media, codec string, mode, gaps, and RANKED cues

The ranking is fixed here, once, and the device never reorders it. Playback
speed changes how far down the list the app gets; it must never change which
story gets told.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from salience import rank_changes, rank_film_cues, describe_at_budget
from speech import synthesize, budget_words


def fragment(src, dst):
    """Rewrite as fragmented mp4, which is what MSE needs to append.

    Handles src and dst being the same file. That happens whenever a bundle is
    regenerated in place — the app asks to describe `content.mp4` and the bundle
    it produces is also `content.mp4` — and ffmpeg refuses to write over its own
    input, which surfaced only as a non-zero exit deep in a background thread.
    """
    same = os.path.exists(dst) and os.path.samefile(src, dst)
    # The temp name must still end in .mp4 — ffmpeg picks the muxer from the
    # extension, and a ".tmp" suffix fails as an argument error rather than a
    # media one, which reads like a corrupt file and is not.
    target = dst.replace(".mp4", ".frag.mp4") if same else dst
    subprocess.run(["ffmpeg", "-y", "-nostdin", "-loglevel", "error",
                    "-i", src, "-c", "copy",
                    "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
                    target], check=True)
    if same:
        os.replace(target, dst)


def video_size(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0:s=x", path],
        capture_output=True, text=True).stdout.strip()
    try:
        w, h = out.split("x")[:2]
        return int(w), int(h)
    except Exception:
        return 1920, 1080


def picture_rect(path, w, h, samples=(0.25, 0.45, 0.65, 0.85)):
    """Where the actual picture is, as fractions of the frame.

    Stream dimensions are not enough. Cinemascope content is routinely
    delivered as 1920x1080 with the letterbox BAKED INTO the image — the Sintel
    trailer carries 12% black top and bottom — so anything drawn in a corner
    lands on a bar the player knows nothing about.

    ffmpeg's cropdetect missed it here entirely, so this measures row luminance
    directly. Several frames are sampled and the SMALLEST letterbox wins: a fade
    or a dark shot would otherwise look like a bar and crop away real picture.
    """
    import numpy as np
    from PIL import Image

    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip() or 0)
    if dur <= 0:
        return {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}

    best_top, best_bottom = None, None
    with tempfile.TemporaryDirectory() as td:
        for i, frac in enumerate(samples):
            png = os.path.join(td, f"s{i}.png")
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{dur * frac:.2f}",
                            "-i", path, "-frames:v", "1", png], check=False)
            if not os.path.exists(png):
                continue
            rows = np.asarray(Image.open(png).convert("L"), dtype=float).mean(axis=1)
            n = len(rows)
            top = 0
            while top < n and rows[top] < 12:
                top += 1
            bottom = n - 1
            while bottom > 0 and rows[bottom] < 12:
                bottom -= 1
            if top >= bottom:           # wholly dark frame, tells us nothing
                continue
            t_frac, b_frac = top / n, (n - 1 - bottom) / n
            best_top = t_frac if best_top is None else min(best_top, t_frac)
            best_bottom = b_frac if best_bottom is None else min(best_bottom, b_frac)

    if best_top is None:
        return {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    # Ignore a couple of stray rows; only report a bar worth avoiding.
    if best_top < 0.02 and best_bottom < 0.02:
        return {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    return {"x": 0.0, "y": round(best_top, 4), "w": 1.0,
            "h": round(1.0 - best_top - best_bottom, 4)}


def codec_string(path):
    """Build the MSE mime type from the actual streams."""
    q = lambda a: subprocess.run(
        ["ffprobe", "-v", "error", *a, "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout.strip()
    prof, lvl = (q(["-select_streams", "v:0", "-show_entries", "stream=profile,level"])
                 .split(",") + ["", ""])[:2]
    table = {"Baseline": 0x42, "Constrained Baseline": 0x42, "Main": 0x4D, "High": 0x64}
    codecs = ["avc1.%02X00%02X" % (table.get(prof, 0x64), int(lvl))]
    if q(["-select_streams", "a:0", "-show_entries", "stream=codec_name"]):
        codecs.append("mp4a.40.2")
    return 'video/mp4; codecs="%s"' % ",".join(codecs)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("judged_json")
    p.add_argument("video")
    p.add_argument("--gaps")
    p.add_argument("--mode", choices=["fit", "pause"], default="fit")
    p.add_argument("--rate", type=float, default=1.0,
                   help="rate the word budgets are written for (fit mode)")
    p.add_argument("--backend", default="anthropic")
    p.add_argument("--out", required=True, help="directory the device fetches from")
    a = p.parse_args()

    os.makedirs(a.out, exist_ok=True)
    raw = json.load(open(a.judged_json))

    # Two producers feed this: the walkthrough path (salience.py -> judged.json,
    # descriptions written later) and the film path (film_cues.py, descriptions
    # already written to the gap they will live in). Normalise here rather than
    # duplicating the exporter.
    if "cues" in raw:
        film = True
        salient = [{"t_to": c["t"], "changed": c["changed"],
                    "description": c["description"]} for c in raw["cues"]]
    else:
        film = False
        salient = [r for r in raw["results"] if r.get("salient")]
    if not salient:
        sys.exit("nothing describable in the input")

    gaps = json.load(open(a.gaps))["gaps"] if a.gaps else []

    print(f"ranking {len(salient)} changes...", file=sys.stderr)
    payload = [{"t": c["t_to"], "changed": c["changed"]} for c in salient]
    order = (rank_film_cues(payload, a.backend) if film
             else rank_changes(payload, a.backend))
    order.sort(key=lambda r: r["rank"])

    media_name = "content.mp4"
    fragment(a.video, os.path.join(a.out, media_name))
    mime = codec_string(os.path.join(a.out, media_name))

    cues = []
    for r in order:
        src = salient[r["index"]]
        # In fit mode the line is written to the gap it will live in; in pause
        # mode there is time, so completeness beats brevity.
        if film:
            # Already written to its gap by film_cues.py; rewriting would only
            # lose the frame context that produced it.
            text = src["description"]
            words = len(text.split())
        elif a.mode == "fit" and gaps:
            t = src["t_to"]
            gap = next((g for g in gaps if g["end"] > t), gaps[-1])
            words = max(2, budget_words(gap["len_s"], a.rate))
            text = describe_at_budget(src["changed"], words, a.backend)
        else:
            words = 14
            text = describe_at_budget(src["changed"], words, a.backend)
        pcm_name = f"desc-{r['rank']:02d}.pcm"
        meta = synthesize(text, os.path.join(a.out, pcm_name))
        cues.append({
            "t": round(src["t_to"], 3),
            "rank": r["rank"],
            "pcm": pcm_name,
            "text": text,
            "duration": meta["duration_s"],
            "caused_by_viewer": r["caused_by_viewer"],
            "why_ranked": r["why"],
        })
        print(f"  #{r['rank']} t={src['t_to']:<6} {'[caused]' if r['caused_by_viewer'] else '        '} "
              f"{meta['words']}w/{meta['duration_s']}s  {text}", file=sys.stderr)

    vw, vh = video_size(os.path.join(a.out, media_name))
    timeline = {
        "media": media_name,
        "mimeCodec": mime,
        "videoWidth": vw,
        "videoHeight": vh,
        "pictureRect": picture_rect(os.path.join(a.out, media_name), vw, vh),
        "mode": a.mode,
        "builtForRate": a.rate,
        "gaps": [{"start": g["start"], "end": g["end"]} for g in gaps],
        "cues": sorted(cues, key=lambda c: c["t"]),
    }
    json.dump(timeline, open(os.path.join(a.out, "timeline.json"), "w"), indent=2)
    print(f"\nbundle -> {a.out}\n  {media_name} ({mime})\n  {len(cues)} cues, "
          f"{len(gaps)} gaps, mode={a.mode}", file=sys.stderr)


if __name__ == "__main__":
    main()
