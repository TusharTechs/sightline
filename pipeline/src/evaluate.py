#!/usr/bin/env python3
"""
Stage 5 — score the run against ground truth.

Two separate questions, deliberately not conflated:

  1. DETECTION  — did the cheap gate notice every moment something changed?
                  A miss here is unrecoverable; nothing downstream can describe
                  a change it never saw.
  2. SALIENCE   — of the changes found, did the model apply the rule correctly?
                  False positives make it chatty. False negatives make it miss
                  the thing that mattered.

Evaluating by task rather than by taste, per the ADP list: the score that counts
is whether a listener could act on the output, and the proxy for that here is
whether the salient state changes are the ones that got described.
"""
import argparse, json, sys

TOLERANCE = 0.6  # seconds; a change detected within this of ground truth matches


def match(gt_events, got_events):
    used, pairs = set(), []
    for g in gt_events:
        best, best_d = None, TOLERANCE
        for i, d in enumerate(got_events):
            if i in used:
                continue
            # distance from the ground-truth instant to the detected interval
            lo, hi = d["t_from"], d["t_to"]
            dist = 0.0 if lo <= g["t"] <= hi else min(abs(g["t"] - lo), abs(g["t"] - hi))
            if dist < best_d:
                best, best_d = i, dist
        if best is not None:
            used.add(best)
        pairs.append((g, got_events[best] if best is not None else None))
    spurious = [d for i, d in enumerate(got_events) if i not in used]
    return pairs, spurious


def main():
    p = argparse.ArgumentParser()
    p.add_argument("ground_truth")
    p.add_argument("--changes", help="detect_changes.py output (detection only)")
    p.add_argument("--judged", help="salience.py output (detection + salience)")
    a = p.parse_args()

    gt = json.load(open(a.ground_truth))
    if a.judged:
        got = json.load(open(a.judged))["results"]
    elif a.changes:
        got = json.load(open(a.changes))["events"]
    else:
        sys.exit("need --changes or --judged")

    pairs, spurious = match(gt["events"], got)

    print(f"\n  ground truth: {len(gt['events'])} events "
          f"({gt['counts']['salient']} salient, {gt['counts']['decoration']} decoration)")
    print(f"  detected:     {len(got)} change events\n")

    hdr = f"  {'t':>5}  {'detected':>8}  {'truth':>9}"
    if a.judged:
        hdr += f"  {'model':>9}  {'':<3}"
    print(hdr + "  what")
    print("  " + "-" * 86)

    det_hits = 0
    sal_tp = sal_fp = sal_fn = sal_tn = 0
    for g, d in pairs:
        found = d is not None
        det_hits += found
        row = f"  {g['t']:>5}  {'yes' if found else 'MISS':>8}  {'salient' if g['salient'] else 'decor':>9}"
        if a.judged:
            m = d.get("salient") if found else None
            row += f"  {str(m):>9}"
            if found and m is not None:
                ok = (m == g["salient"])
                row += f"  {'ok' if ok else '!!':<3}"
                if g["salient"] and m: sal_tp += 1
                elif g["salient"] and not m: sal_fn += 1
                elif not g["salient"] and m: sal_fp += 1
                else: sal_tn += 1
            else:
                row += f"  {'-':<3}"
        print(row + f"  {g['what'][:44]}")

    print(f"\n  DETECTION   {det_hits}/{len(gt['events'])} ground-truth changes found"
          f"   ({len(spurious)} extra not in ground truth)")
    if spurious:
        for s in spurious[:8]:
            note = s.get("changed") or f"{s['changed_px']} px at {s['bbox']}"
            print(f"              extra at t={s['t_from']}-{s['t_to']}s  {note[:52]}")

    if a.judged and (sal_tp + sal_fp + sal_fn + sal_tn):
        prec = sal_tp / (sal_tp + sal_fp) if (sal_tp + sal_fp) else 0.0
        rec = sal_tp / (sal_tp + sal_fn) if (sal_tp + sal_fn) else 0.0
        print(f"  SALIENCE    correct on {sal_tp + sal_tn}/"
              f"{sal_tp + sal_fp + sal_fn + sal_tn} matched events")
        print(f"              precision {prec:.2f} (spoke when it shouldn't: {sal_fp})")
        print(f"              recall    {rec:.2f} (stayed silent when it mattered: {sal_fn})")
    print()


if __name__ == "__main__":
    main()
