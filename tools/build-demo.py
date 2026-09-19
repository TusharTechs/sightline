#!/usr/bin/env python3
"""Assemble the demo video from the recorded takes, cards and narration.

Declarative on purpose: the EDIT list below is the whole edit. Re-record a
scene, re-run this, and the cut is rebuilt in the same shape rather than
reconstructed by hand from memory.

Narration is synthesised separately (Polly, Stephen) into build/demo/vo.
A different voice from the descriptions on purpose -- the descriptions are a
female voice, and a judge should never be unsure which of the two they are
listening to.
"""
import json, os, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAKES = os.path.expanduser("~/Desktop/sightline-takes")
BUILD = os.path.join(ROOT, "build", "demo")
VO = os.path.join(BUILD, "vo")
CARDS = os.path.join(BUILD, "cards")
SEGS = os.path.join(BUILD, "segs")
W, H = 1920, 1080
BG = (11, 15, 20)
INK = (242, 245, 248)
DIM = (143, 161, 179)
ACCENT = (61, 220, 151)
SF = "/System/Library/Fonts/SFNS.ttf"

def font(sz, weight=400):
    f = ImageFont.truetype(SF, sz)
    try:
        f.set_variation_by_axes([weight])
    except Exception:
        pass
    return f

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"FAILED: {' '.join(cmd[:6])}...\n{r.stderr[-1500:]}")

def dur(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration", "-of", "default=nw=1:nk=1", path],
                         capture_output=True, text=True).stdout.strip()
    return float(out)

# ---------------------------------------------------------------- cards

def centre(d, y, text, f, fill=INK, spacing=12):
    lines = text.split("\n")
    for line in lines:
        w = d.textlength(line, font=f)
        d.text(((W - w) / 2, y), line, font=f, fill=fill)
        y += f.size + spacing
    return y

def card_mark(path, sub=None):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    logo = Image.open(os.path.join(ROOT, "app/assets/image/sightline.png")).convert("RGBA")
    logo = logo.resize((190, 190))
    im.paste(logo, ((W - 190) // 2, 360), logo)
    y = centre(d, 585, "Sightline", font(96, 700))
    if sub:
        centre(d, y + 18, sub, font(40, 400), DIM)
    im.save(path)

def card_text(path, big, small=None, accent=None):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    y = centre(d, 430 if small else 480, big, font(76, 600))
    if small:
        centre(d, y + 26, small, font(38, 400), DIM)
    im.save(path)

def card_table(path):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    centre(d, 170, "Measured, not claimed", font(58, 600), DIM)
    rows = [("An animated film", "4% dialogue", "24 descriptions"),
            ("A 1951 instructional film", "77% dialogue", "11 descriptions"),
            ("A one-minute advert", "77% dialogue", "none")]
    x1, x2, x3 = 300, 1080, 1450
    y = 330
    fh = font(44, 600); fb = font(40, 400)
    for name, pct, n in rows:
        d.text((x1, y), name, font=fb, fill=INK)
        d.text((x2, y), pct, font=fb, fill=DIM)
        col = ACCENT if n != "none" else (240, 139, 126)
        d.text((x3, y), n, font=fh, fill=col)
        y += 96
        d.line([(x1, y - 26), (W - x1, y - 26)], fill=(42, 49, 58), width=2)
    centre(d, y + 40, "It fills every second it has room for.", font(40, 400), DIM)
    im.save(path)

def card_end(path):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    logo = Image.open(os.path.join(ROOT, "app/assets/image/sightline.png")).convert("RGBA")
    logo = logo.resize((140, 140))
    im.paste(logo, ((W - 140) // 2, 300), logo)
    y = centre(d, 470, "Sightline", font(78, 700))
    y = centre(d, y + 30, "tushartechs.github.io/sightline", font(44, 400), ACCENT)
    y = centre(d, y + 16, "github.com/TusharTechs/sightline", font(38, 400), DIM)
    centre(d, y + 40, "Sintel © Blender Foundation, CC-BY 3.0", font(30, 400), (110, 122, 136))
    im.save(path)

# ---------------------------------------------------------------- the edit
#
# (source, start, length, [(vo_name, at_seconds), ...], bed_gain)
# bed_gain ducks the clip's own audio under narration. 1.0 leaves it alone,
# which is what the described passage and the answer need -- those ARE the
# point of their scenes.

T = lambda n: os.path.join(TAKES, n)
S1 = T("scene-1-gap-145644.mov")
S2 = T("scene-2-generation-152402.mov")
S3 = T("scene-3-described-145903.mov")
S4TV = T("scene-4tv-handoff-150051.mov")
S4P = T("scene-4phone-clean.mov")
S5 = T("scene-5-plate-150309.mov")

EDIT = [
    ("s01", S1,   0.0,  7.0,  [],                                 1.0),
    ("s02", S5,   0.0,  8.2,  [("01_gap", 0.3)],                  0.22),
    ("s03", S5,   8.2, 15.0,  [("02_exists", 0.3)],               0.22),
    ("s04", "CARD:mark", 0, 6.6, [("03_built", 0.3)],             0.0),
    ("s05", S2,   0.0, 18.0,  [("04_generating", 7.5)],           0.55),
    ("s06", "CARD:later", 0, 2.5, [],                             0.0),
    ("s07", S3,   0.0, 16.0,  [("05_same", 0.5)],                 1.0),
    ("s08", S4TV, 0.0, 18.0,  [("06_tworoom", 0.5), ("07_ask", 8.3)], 0.30),
    ("s09", S4P,  0.0, 20.0,  [],                                 1.0),
    ("s10", S5,  23.2, 38.8,  [("09_reviewers", 0.3), ("10_dave", 7.8),
                               ("11_watcher", 18.4), ("12_credit", 28.2),
                               ("13_measured", 36.4)],            0.16),
    ("s11", "CARD:table", 0, 13.6, [("14_table", 0.3)],           0.0),
    ("s12", S5,  62.0,  5.2,  [("15_limit", 0.3)],                0.16),
    ("s13", "CARD:close", 0, 6.4, [("16_close", 0.3)],            0.0),
    ("s14", "CARD:end", 0, 4.0, [("17_name", 0.3)],               0.0),
]

def build():
    for d in (BUILD, CARDS, SEGS):
        os.makedirs(d, exist_ok=True)
    card_mark(f"{CARDS}/mark.png", "Audio description for content that has none.")
    card_text(f"{CARDS}/later.png", "Three minutes later", "It really takes that long.")
    card_table(f"{CARDS}/table.png")
    card_mark(f"{CARDS}/close.png")
    card_end(f"{CARDS}/end.png")

    parts = []
    for name, src, start, length, vos, bed in EDIT:
        out = f"{SEGS}/{name}.mov"
        fit = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
               f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x0b0f14,fps=30,setsar=1")
        cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-y"]
        if str(src).startswith("CARD:"):
            cmd += ["-loop", "1", "-t", f"{length}", "-i",
                    f"{CARDS}/{src.split(':')[1]}.png",
                    "-f", "lavfi", "-t", f"{length}", "-i",
                    "anullsrc=r=48000:cl=stereo"]
            vidx, aidx = "0:v", "1:a"
        else:
            cmd += ["-ss", f"{start}", "-t", f"{length}", "-i", src]
            vidx, aidx = "0:v", "0:a"

        filters = [f"[{vidx}]{fit}[v]"]
        amix = [f"[{aidx}]volume={bed}[bed]"]
        labels = ["[bed]"]
        for i, (vo, at) in enumerate(vos):
            cmd += ["-i", f"{VO}/{vo}.mp3"]
            n = len(cmd) // 1  # placeholder; index computed below
        base = 2 if str(src).startswith("CARD:") else 1
        for i, (vo, at) in enumerate(vos):
            idx = base + i
            amix.append(f"[{idx}:a]adelay={int(at*1000)}|{int(at*1000)},volume=1.35[vo{i}]")
            labels.append(f"[vo{i}]")
        amix.append(f"{''.join(labels)}amix=inputs={len(labels)}:dropout_transition=0:"
                    f"normalize=0,atrim=0:{length},asetpts=N/SR/TB[a]")
        cmd += ["-filter_complex", ";".join(filters + amix),
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                "-ar", "48000", "-ac", "2", out]
        run(cmd)
        parts.append(out)
        print(f"  {name:<5} {dur(out):5.1f}s  {os.path.basename(str(src))}")

    listfile = f"{BUILD}/parts.txt"
    with open(listfile, "w") as f:
        for p in parts:
            f.write(f"file '{p}'\n")
    final = os.path.expanduser("~/Desktop/sightline-demo.mp4")
    run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-f", "concat",
         "-safe", "0", "-i", listfile,
         "-c:v", "libx264", "-preset", "medium", "-crf", "19",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-movflags", "+faststart", final])
    print(f"\n  FINAL {dur(final):.1f}s -> {final}")

if __name__ == "__main__":
    build()
