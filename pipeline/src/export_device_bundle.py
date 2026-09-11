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
import argparse, json, os, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from salience import rank_changes, describe_at_budget
from speech import synthesize, budget_words


def fragment(src, dst):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-c", "copy",
                    "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
                    dst], check=True)


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
    salient = [r for r in json.load(open(a.judged_json))["results"] if r.get("salient")]
    if not salient:
        sys.exit("no salient changes in the judged file")

    gaps = json.load(open(a.gaps))["gaps"] if a.gaps else []

    print(f"ranking {len(salient)} changes...", file=sys.stderr)
    order = rank_changes([{"t": c["t_to"], "changed": c["changed"]} for c in salient],
                         a.backend)
    order.sort(key=lambda r: r["rank"])

    media_name = "content.mp4"
    fragment(a.video, os.path.join(a.out, media_name))
    mime = codec_string(os.path.join(a.out, media_name))

    cues = []
    for r in order:
        src = salient[r["index"]]
        # In fit mode the line is written to the gap it will live in; in pause
        # mode there is time, so completeness beats brevity.
        if a.mode == "fit" and gaps:
            t = src["t_to"]
            gap = next((g for g in gaps if g["end"] > t), gaps[-1])
            words = max(2, budget_words(gap["len_s"], a.rate))
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

    timeline = {
        "media": media_name,
        "mimeCodec": mime,
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
