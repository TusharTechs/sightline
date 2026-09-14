#!/usr/bin/env python3
"""Score a sorting test against its key.

    shape_score.py KEY_DIR --arrived 1,4,7 --built 2,3,5

Reports accuracy and the probability of doing at least that well by guessing,
which is the only number that says whether the distinction was audible.
"""
import argparse, json, os
from math import comb


def main():
    p = argparse.ArgumentParser()
    p.add_argument("dir")
    p.add_argument("--arrived", required=True, help="clip numbers heard as events")
    p.add_argument("--built", required=True, help="clip numbers heard as music")
    a = p.parse_args()

    key = json.load(open(os.path.join(a.dir, "key.json")))
    said = {}
    for n in a.arrived.split(","):
        if n.strip():
            said[int(n)] = "hit"
    for n in a.built.split(","):
        if n.strip():
            said[int(n)] = "swell"

    right = wrong = 0
    print("   clip  you said   code said   attack   fell@2s")
    for i, k in enumerate(key, 1):
        mine = said.get(i)
        if mine is None:
            continue
        ok = mine == k["answer"]
        right += ok
        wrong += not ok
        f2 = k.get("above_floor_2s_db")
        print(f"   {i:>4}  {mine:<9}  {k['answer']:<9}  {'ok' if ok else 'MISS':>4}"
              f"  {str(k['attack_ms'])+'ms':>7}  "
              f"{(str(f2)+'dB') if f2 is not None else '-':>8}   t={k['t']}s")

    n = right + wrong
    if not n:
        return
    # One-sided binomial: how often would guessing do at least this well?
    p_val = sum(comb(n, i) for i in range(right, n + 1)) / 2 ** n
    print(f"\n  {right}/{n} correct")
    print(f"  by guessing alone, that or better happens {p_val:.1%} of the time")
    if p_val < 0.05:
        print("  -> the difference the code makes is audible")
    else:
        print("  -> this does not show the difference is audible")


if __name__ == "__main__":
    main()
