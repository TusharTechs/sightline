#!/usr/bin/env python3
"""
Stage 2+3 — salience judgement and change description.

The rule, adopted verbatim from a blind accessibility professional on the ACB
ADP list, is the whole design:

    A change matters when it changes what you can do next.

Counts: a box got ticked, a button went from greyed out to live, a dialog opened
and nothing else will respond until it's dealt with. Doesn't count: a highlight
moving, a hover, a scroll, a transient tooltip.

The same rule decides whether to pause, so this stage drives both.

Model access is pluggable. `claude` runs through the local CLI and works today;
`bedrock` is the intended path for submission but needs credentials and a CA
bundle that tolerates the local TLS setup.
"""
import argparse, base64, json, os, re, subprocess, sys, tempfile
from PIL import Image

RULE = """A change matters when it changes what the viewer can do next.

COUNTS as salient (describe it):
- a checkbox or toggle changed state
- a control went from disabled to enabled, or enabled to disabled
- a dialog, menu or overlay opened or closed
- content was added, removed, or finished loading
- an error, confirmation or status message appeared

Does NOT count as salient (stay silent):
- a focus ring or highlight moved
- a hover state, or a tooltip appearing or disappearing
- the page scrolled, revealing content that already existed
- a purely cosmetic animation or transition"""

PROMPT = """You are generating audio description for a software walkthrough, for a
viewer who cannot see the screen.

Two frames are given: BEFORE and AFTER. Describe what CHANGED between them, not
what is on screen. Then judge whether that change is salient.

{rule}

Answer with a single JSON object and nothing else:
{{
  "changed": "<what visibly changed, one short clause>",
  "salient": true|false,
  "reason": "<why it does or does not change what the viewer can do next>",
  "description": "<what to say aloud, at most {max_words} words; empty string if not salient>"
}}

The description is spoken, so: plain words, present tense, no UI jargon like
'widget' or 'element', and never mention frames, pixels or the screen itself."""


def crop_pair(before, after, bbox, pad=40):
    """Crop both frames to the changed region, with a little context."""
    outs = []
    with Image.open(before) as b:
        W, H = b.size
    x0, y0, x1, y1 = bbox
    box = (max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad))
    for src, tag in ((before, "before"), (after, "after")):
        f = tempfile.NamedTemporaryFile(suffix=f"_{tag}.png", delete=False)
        with Image.open(src) as im:
            im.crop(box).save(f.name)
        outs.append(f.name)
    return outs


def _extract_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"no JSON in model output: {text[:400]}")
    return json.loads(m.group(0))


def judge_claude_cli(before_png, after_png, max_words=14, timeout=180):
    prompt = (PROMPT.format(rule=RULE, max_words=max_words)
              + f"\n\nBEFORE frame: {before_png}\nAFTER frame: {after_png}\n"
                "Read both images, then answer.")
    r = subprocess.run(
        ["claude", "-p", prompt, "--allowedTools", "Read"],
        capture_output=True, text=True, timeout=timeout,
    )
    if r.returncode != 0:
        raise RuntimeError(f"claude cli failed: {r.stderr[:400]}")
    return _extract_json(r.stdout)


BACKENDS = {"claude": judge_claude_cli}


def run(frames_dir, changes_json, fps, backend="claude", max_words=14, limit=None):
    data = json.load(open(changes_json))
    events = data["events"][:limit] if limit else data["events"]
    judge = BACKENDS[backend]
    results = []
    for e in events:
        bi, ai = int(round(e["t_from"] * fps)), int(round(e["t_to"] * fps))
        bp = os.path.join(frames_dir, f"f{bi:04d}.png")
        ap = os.path.join(frames_dir, f"f{ai:04d}.png")
        cb, ca = crop_pair(bp, ap, e["bbox"])
        try:
            verdict = judge(cb, ca, max_words)
        except Exception as ex:
            verdict = {"changed": "", "salient": None, "reason": f"ERROR: {ex}",
                       "description": ""}
        finally:
            for f in (cb, ca):
                try: os.unlink(f)
                except OSError: pass
        results.append({**{k: e[k] for k in ("id", "t_from", "t_to", "bbox", "changed_px")},
                        **verdict})
        print(f"  [{e['id']}] t={e['t_from']:>5}s  salient={verdict.get('salient')}  "
              f"{verdict.get('changed','')[:60]}", file=sys.stderr)
    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument("frames_dir")
    p.add_argument("changes_json")
    p.add_argument("--fps", type=float, required=True)
    p.add_argument("--backend", default="claude", choices=list(BACKENDS))
    p.add_argument("--max-words", type=int, default=14)
    p.add_argument("--limit", type=int)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    res = run(a.frames_dir, a.changes_json, a.fps, a.backend, a.max_words, a.limit)
    json.dump({"backend": a.backend, "results": res}, open(a.out, "w"), indent=2)
    print(f"{len(res)} judged -> {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
