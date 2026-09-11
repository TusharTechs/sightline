#!/usr/bin/env python3
"""
Stage 1 — the change gate.

Finds moments where the screen changed, and where on the screen. It makes NO
judgement about whether a change matters: a scroll and a ticked checkbox both
come out of here as changes. Salience is decided downstream, by a model, using
the rule "a change matters when it changes what you can do next".

The gate is deliberately sensitive and cheap. Its job is to turn thousands of
frame pairs into a handful of candidate moments with tight bounding boxes, so
the expensive stage only ever sees crops that actually differ.

Output: JSON list of change events, each with the frame pair that brackets it
and the region that changed.
"""
import argparse, json, os, sys
import numpy as np
from PIL import Image

# A pixel counts as changed if it moves more than this (0-255).
PIXEL_DELTA = 16
# Ignore changes smaller than this many pixels — antialiasing, cursor blink.
MIN_CHANGED_PX = 120
# Frames this close together belong to the same logical event.
MERGE_GAP_FRAMES = 2
# Largest vertical scroll we try to recognise, in pixels.
MAX_SCROLL_PX = 400
# A shift only counts as a scroll if it explains the change this much better
# than no shift at all.
SCROLL_GAIN = 3.0


def load_gray(path):
    return np.asarray(Image.open(path).convert("L"), dtype=np.int16)


def changed_mask(a, b):
    return np.abs(a - b) > PIXEL_DELTA


def bbox_of(mask):
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    if not rows.any():
        return None
    y0, y1 = np.where(rows)[0][[0, -1]]
    x0, x1 = np.where(cols)[0][[0, -1]]
    return [int(x0), int(y0), int(x1) + 1, int(y1) + 1]


def scroll_shift(a, b, bbox=None):
    """Detect vertical translation within the changed region.

    Two crops cannot distinguish "this row scrolled out of view" from "this row
    was removed" — and those mean opposite things under the salience rule, since
    a removed control changes what you can do and a scrolled one does not. The
    pixels know the difference, so measure it here and pass it on rather than
    leaving the model to guess.

    Correlates row-mean profiles and returns the shift in pixels, or 0.

    Restricted to the changed region on purpose: in a typical UI only a panel
    scrolls while the chrome around it stays put, and a whole-frame profile is
    dominated by the static majority — measured at 1.00x gain versus 4.04x
    inside the region for the same scroll.
    """
    if bbox:
        x0, y0, x1, y1 = bbox
        a, b = a[y0:y1, x0:x1], b[y0:y1, x0:x1]
    if a.shape[0] < 16:
        return 0
    pa = a.mean(axis=1).astype(np.float64)
    pb = b.mean(axis=1).astype(np.float64)
    pa -= pa.mean()
    pb -= pb.mean()
    base = float(np.abs(pa - pb).mean())
    if base < 1e-6:
        return 0
    best_dy, best_err = 0, base
    for dy in range(-MAX_SCROLL_PX, MAX_SCROLL_PX + 1):
        if dy == 0:
            continue
        if dy > 0:
            x, y = pa[dy:], pb[:-dy]
        else:
            x, y = pa[:dy], pb[-dy:]
        if x.size < a.shape[0] // 3:      # need substantial overlap
            continue
        err = float(np.abs(x - y).mean())
        if err < best_err:
            best_dy, best_err = dy, err
    if best_dy and best_err * SCROLL_GAIN < base:
        return best_dy
    return 0


def detect(frames_dir, fps):
    files = sorted(f for f in os.listdir(frames_dir) if f.endswith(".png"))
    if len(files) < 2:
        sys.exit(f"need at least 2 frames in {frames_dir}, found {len(files)}")

    raw = []
    prev = load_gray(os.path.join(frames_dir, files[0]))
    for i in range(1, len(files)):
        cur = load_gray(os.path.join(frames_dir, files[i]))
        mask = changed_mask(prev, cur)
        n = int(mask.sum())
        if n >= MIN_CHANGED_PX:
            raw.append({
                "i_from": i - 1, "i_to": i,
                "changed_px": n,
                "frac": round(n / mask.size, 5),
                "bbox": bbox_of(mask),
            })
        prev = cur

    # Merge frame-adjacent detections into single events (a fade or a transition
    # spans several frames but is one thing that happened).
    events, cur_ev = [], None
    for d in raw:
        if cur_ev and d["i_from"] - cur_ev["i_to"] <= MERGE_GAP_FRAMES:
            cur_ev["i_to"] = d["i_to"]
            cur_ev["changed_px"] = max(cur_ev["changed_px"], d["changed_px"])
            cur_ev["frac"] = max(cur_ev["frac"], d["frac"])
            bb, nb = cur_ev["bbox"], d["bbox"]
            cur_ev["bbox"] = [min(bb[0], nb[0]), min(bb[1], nb[1]),
                              max(bb[2], nb[2]), max(bb[3], nb[3])]
        else:
            if cur_ev:
                events.append(cur_ev)
            cur_ev = dict(d)
    if cur_ev:
        events.append(cur_ev)

    # Annotate each event with any whole-region vertical translation.
    for e in events:
        a = load_gray(os.path.join(frames_dir, files[e["i_from"]]))
        b = load_gray(os.path.join(frames_dir, files[e["i_to"]]))
        e["scroll_dy"] = scroll_shift(a, b, e["bbox"])

    for n, e in enumerate(events):
        e["id"] = n
        e["t_from"] = round(e.pop("i_from") / fps, 4)
        e["t_to"] = round(e.pop("i_to") / fps, 4)
        x0, y0, x1, y1 = e["bbox"]
        e["bbox_wh"] = [x1 - x0, y1 - y0]
    return events


def main():
    p = argparse.ArgumentParser()
    p.add_argument("frames_dir")
    p.add_argument("--fps", type=float, required=True)
    p.add_argument("--out", default="-")
    a = p.parse_args()
    events = detect(a.frames_dir, a.fps)
    blob = json.dumps({"fps": a.fps, "count": len(events), "events": events}, indent=2)
    if a.out == "-":
        print(blob)
    else:
        open(a.out, "w").write(blob)
        print(f"{len(events)} change events -> {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
