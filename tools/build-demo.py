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
import numpy as np
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
# Recorded by hand rather than by the script. macOS screen recording does not
# starve its audio the way a single ffmpeg capturing screen-and-audio does:
# this one decodes 17.10s of audio for a 17.13s container, against roughly 10%
# short on the scripted takes. Cut at an offset of +5.0s, established by
# finding the frame where the caption changes from the 85.01 cue to the 90.27
# cue -- audio correlation could not lock on and its answer of +1.7s put the
# wrong line on screen.
S3 = T("scene-3-described-user.mov")
S4TV = T("scene-4tv-handoff-150051.mov")
S4P = T("scene-4phone-clean.mov")
S5 = T("scene-5-plate-150309.mov")

# (name, source, in-point, minimum length, [(vo, at)], bed gain)
#
# The length is a MINIMUM. The builder extends a segment so the last narration
# line finishes inside it, because the first cut trimmed one off mid-sentence:
# five lines were placed by hand into 38.8 seconds and the fifth needed 40.
#
# Placements avoid the device's own voice rather than ducking under it. Two
# voices at once reads as a fault, not as layering. Measured in the takes:
# the app speaks its offer at 2.6-7.0s and its stage line at 13.3-14.5s of the
# generation take, and announces the handoff in the first seven seconds of the
# phone-handoff take. Narration goes in the gaps between those.
EDIT = [
    ("s01", S1,   0.0,  7.0,  [],                                 1.0),
    ("s02", S5,   0.0,  8.0,  [("01_gap", 0.3)],                  0.22),
    ("s03", S5,   8.2, 14.9,  [("02_exists", 0.3)],               0.22),
    ("s04", "CARD:mark", 0, 6.5, [("03_built", 0.3)],             0.0),
    # 04a lands in the 7.0-13.3 gap; 04b after the stage line ends at 14.5.
    # bed at full: the app's stage line is quieter than its offer, and ducking
    # to 0.55 put it under the floor entirely -- silent in the one scene whose
    # point is the app narrating itself. Nothing is spoken over it now.
    ("s05", S2,   0.0, 16.0,  [("04a_doing", 7.6), ("04b_how", 15.0)], 1.0),
    ("s06", "CARD:later", 0, 2.0, [],                             0.0),
    # 14.9, not 14.0: a description runs 13.24-14.61 in this take and cutting
    # at 14.0 sliced it mid-word -- which is the break at 1:14 in the first cut.
    ("s07", S3,   0.0, 17.1,  [("05_same", 0.5)],                 1.0),
    # after the handoff announcement, not over it.
    ("s08", S4TV, 0.0, 16.2,  [("06_tworoom", 8.0)],              0.85),
    # the answer starts 6.5s in; this has to be finished before it.
    ("s09", S4P,  0.0, 17.5,  [("07b_ask", 0.2)],                 1.0),
    ("s10", S5,  23.2, 38.0,  [("09_reviewers", 0.3), ("10_dave", 7.7),
                               ("11_watcher", 18.2), ("12_credit", 27.9),
                               ("13_measured", 36.0)],            0.16),
    ("s11", "CARD:table", 0, 13.5, [("14_table", 0.3)],           0.0),
    ("s12", S5,  62.0,  5.0,  [("15_limit", 0.3)],                0.16),
    ("s13", "CARD:close", 0, 6.3, [("16_close", 0.3)],            0.0),
    ("s14", "CARD:end", 0, 2.0, [("17_name", 0.3)],               0.0),
]

TAIL = 0.45
VFADE = 0.38          # dip through black where the picture jumps
AFADE = 0.22          # shorter, so nothing spoken gets clipped          # breathing room after the last line in a segment
LIMIT = 180.0        # the rules say under three minutes


# ---------------------------------------------------------------- music
#
# Dreamscape (Density & Time, YouTube Audio Library). Chosen by measurement,
# not by ear: of the nine candidates it puts only 11.1% of its energy in
# 200Hz-4kHz, where speech lives. The rest sit between 51% and 98.9% -- one of
# them, Stillness, is 98.9% and would have masked every description in the
# film while sounding perfectly pleasant on its own.
#
# It does climb about 11dB over its length, so the bed is drawn from after the
# opening ramp and then level-corrected against its own envelope. What is left
# is a constant floor rather than something that creeps up under the narration.
MUSIC = "dreamscape"
MUSIC_FROM = 60.0        # past the opening ramp

# Target RMS per segment, in dBFS. None means silence -- and the three Nones
# are the argument of the film:
#   s01  the seven seconds with no description. Scoring it destroys the point.
#   s07  the described passage. This is the exhibit.
#   s09  the phone answering a question. Also the exhibit.
MUSIC_DB = {
    "s01": None,   "s02": -41.0, "s03": -41.0, "s04": -37.0,
    "s05": -45.0,  # the app narrating itself; present, never competing
    "s06": -33.0,  # a card with nothing spoken over it
    "s07": None,   "s08": -43.0, "s09": None,  "s10": -41.0,
    "s11": -37.0,  "s12": -41.0, "s13": -37.0, "s14": -33.0,
}
RAMP = 0.9               # seconds to fade in or out of a region


def build_music_bed(plan, out_wav):
    """A bed that holds one level, and gets out of the way three times."""
    import wave
    src = f"{BUILD}/music/{MUSIC}.wav"
    w = wave.open(src, "rb")
    sr = w.getframerate()
    raw = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    w.close()
    a = raw.astype(np.float32).reshape(-1, 2) / 32768.0
    a = a[int(MUSIC_FROM * sr):]

    total = sum(p[3] for p in plan)
    need = int(total * sr) + sr
    while len(a) < need:                       # loop if the track runs out
        a = np.concatenate([a, a])
    a = a[:need]

    # Flatten the track's own drift: measure a slow RMS and divide it out.
    win = int(3.0 * sr)
    mono = a.mean(axis=1)
    centres, levels = [], []
    for i in range(0, len(mono) - win, win // 2):
        centres.append(i + win // 2)
        levels.append(max(np.sqrt((mono[i:i + win] ** 2).mean()), 1e-5))
    env = np.interp(np.arange(len(mono)), centres, levels)
    ref = 10 ** (-20.0 / 20.0)
    correction = np.clip(ref / env, 0.0, 10 ** (12.0 / 20.0))
    a = a * correction[:, None]

    # Per-segment target, with ramps built INSIDE each region.
    #
    # Not a smoothing pass over the whole envelope: convolution bleeds a
    # fade-in backwards across the boundary, and the first region is the seven
    # seconds of silence that the whole film argues from. It measured -56dBFS
    # instead of nothing. Ramps drawn inside each region cannot leak into the
    # one next door.
    gain = np.zeros(len(mono), dtype=np.float32)
    k = int(RAMP * sr)
    bounds, t = [], 0.0
    for name, _src, _st, length, _vos, _bed in plan:
        bounds.append((name, t, t + length))
        t += length
    for idx, (name, t0, t1) in enumerate(bounds):
        db = MUSIC_DB.get(name)
        if db is None:
            continue
        lin = 10 ** ((db + 20.0) / 20.0)
        i0, i1 = int(t0 * sr), min(int(t1 * sr), len(gain))
        gain[i0:i1] = lin
        prev_db = MUSIC_DB.get(bounds[idx - 1][0]) if idx else None
        next_db = MUSIC_DB.get(bounds[idx + 1][0]) if idx + 1 < len(bounds) else None
        n = min(k, (i1 - i0) // 2)
        if n > 0 and prev_db is None:
            gain[i0:i0 + n] *= np.linspace(0.0, 1.0, n, dtype=np.float32)
        if n > 0 and next_db is None:
            gain[i1 - n:i1] *= np.linspace(1.0, 0.0, n, dtype=np.float32)
    # ease the steps between two regions that both have music
    sm = int(0.35 * sr)
    if sm > 1:
        gain = np.convolve(gain, np.ones(sm, dtype=np.float32) / sm, mode="same")
    # and make absolutely certain the silent regions are silent
    for name, t0, t1 in bounds:
        if MUSIC_DB.get(name) is None:
            gain[int(t0 * sr):min(int(t1 * sr), len(gain))] = 0.0
    a = a * gain[:, None]

    out = wave.open(out_wav, "wb")
    out.setnchannels(2); out.setsampwidth(2); out.setframerate(sr)
    out.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())
    out.close()
    return out_wav


def build():
    for d in (BUILD, CARDS, SEGS):
        os.makedirs(d, exist_ok=True)
    card_mark(f"{CARDS}/mark.png", "Audio description for content that has none.")
    card_text(f"{CARDS}/later.png", "Three minutes later", "It really takes that long.")
    card_table(f"{CARDS}/table.png")
    card_mark(f"{CARDS}/close.png")
    card_end(f"{CARDS}/end.png")

    plan = []
    for name, src, start, min_len, vos, bed in EDIT:
        need = max([vo_at + dur(f"{VO}/{vo}.mp3") + TAIL for vo, vo_at in vos],
                   default=0.0)
        length = round(max(min_len, need), 2)
        # Chain consecutive pieces of the same shot. A segment's length is
        # driven by its narration, so it rarely ends exactly where the next
        # one was written to start -- s02 ran to 8.4s while s03 began at 8.2,
        # repeating a fifth of a second and, worse, reading as a jump so the
        # transition logic dipped to black in the middle of one continuous
        # shot. Snap the start instead.
        if plan:
            pname, psrc, pstart, plen, _pv, _pb = plan[-1]
            if psrc == src and abs(start - (pstart + plen)) < 1.0:
                start = round(pstart + plen, 2)
        plan.append((name, src, start, length, vos, bed))
    total = sum(p[3] for p in plan)
    print(f"  planned runtime {total:.1f}s" +
          ("" if total <= LIMIT else f"  OVER the {LIMIT:.0f}s limit by {total-LIMIT:.1f}s"))
    if total > LIMIT:
        sys.exit("refusing to build a cut that breaks the rule")

    # A cut is only invisible when the next shot carries on from this one.
    # Everywhere else the picture jumps -- at 78s it went backwards 25 seconds
    # in the film mid-scene, which reads as a glitch rather than an edit. Dip
    # through black at every boundary that is not a continuation, so the move
    # is something the viewer is told about rather than something they catch.
    def continues(prev, cur):
        if prev is None:
            return False
        pname, psrc, pstart, plen, _v, _b = prev
        cname, csrc, cstart, clen, _v2, _b2 = cur
        if str(psrc).startswith("CARD:") or str(csrc).startswith("CARD:"):
            return False
        return psrc == csrc and abs(cstart - (pstart + plen)) < 0.05

    parts = []
    for idx, (name, src, start, length, vos, bed) in enumerate(plan):
        prev = plan[idx - 1] if idx else None
        nxt = plan[idx + 1] if idx + 1 < len(plan) else None
        fade_in = not continues(prev, plan[idx])
        fade_out = nxt is None or not continues(plan[idx], nxt)
        out = f"{SEGS}/{name}.mov"
        fit = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
               f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x0b0f14,fps=30,setsar=1")
        if fade_in:
            fit += f",fade=t=in:st=0:d={VFADE}:color=0x0b0f14"
        if fade_out:
            fit += f",fade=t=out:st={max(0.0, length - VFADE):.3f}:d={VFADE}:color=0x0b0f14"
        cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-y"]
        if str(src).startswith("CARD:"):
            cmd += ["-loop", "1", "-t", f"{length}", "-i",
                    f"{CARDS}/{src.split(':')[1]}.png",
                    "-f", "lavfi", "-t", f"{length}", "-i",
                    "anullsrc=r=48000:cl=stereo"]
            vidx, aidx = "0:v", "1:a"
        else:
            # Pull the bed out first, put the timestamps back, and fill the
            # dropouts before it goes anywhere near the mix.
            # aresample only. Nothing is "repaired" here any more.
            #
            # A previous version hunted short silences with speech either side
            # and filled them, on the theory that they were capture dropouts.
            # They were not: a 12s continuous tone through the same path came
            # back with one dropout, and the 101 found across the cut all sat
            # in the 80-120ms band, which is where ordinary gaps between words
            # live. So it was filling real pauses with copies of the
            # neighbouring syllables -- which is what an echo is.
            bed_wav = f"{SEGS}/{name}_bed.wav"
            run(["ffmpeg", "-hide_banner", "-v", "error", "-y",
                 "-ss", f"{start}", "-t", f"{length}", "-i", src, "-vn",
                 "-af", "aresample=async=1:first_pts=0",
                 "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", bed_wav])
            cmd += ["-ss", f"{start}", "-t", f"{length}", "-i", src, "-i", bed_wav]
            vidx, aidx = "0:v", "1:a"

        filters = [f"[{vidx}]{fit}[v]"]
        # aresample=async=1 before anything else.
        #
        # The screen captures are short of samples -- BlackHole does not
        # deliver during silence, so a 62s take decodes to 54.7s of audio. The
        # packets carry correct timestamps and a player stays in sync, but a
        # filter chain that just decodes collapses every gap and drags all the
        # audio earlier. That is what broke the voiceover: narration written
        # against the clock landed over the device's own voice, and the stage
        # line went missing entirely because by then the bed had run out.
        # This materialises the gaps as real silence and puts the clock back.
        amix = [f"[{aidx}]volume={bed}[bed]"]
        labels = ["[bed]"]
        for i, (vo, at) in enumerate(vos):
            cmd += ["-i", f"{VO}/{vo}.mp3"]
            n = len(cmd) // 1  # placeholder; index computed below
        base = 2   # both branches now have exactly two inputs before the VOs
        for i, (vo, at) in enumerate(vos):
            idx = base + i
            amix.append(f"[{idx}:a]adelay={int(at*1000)}|{int(at*1000)},volume=1.35[vo{i}]")
            labels.append(f"[vo{i}]")
        afades = ""
        if fade_in:
            afades += f",afade=t=in:st=0:d={AFADE}"
        if fade_out:
            afades += f",afade=t=out:st={max(0.0, length - AFADE):.3f}:d={AFADE}"
        amix.append(f"{''.join(labels)}amix=inputs={len(labels)}:dropout_transition=0:"
                    f"normalize=0,atrim=0:{length},asetpts=N/SR/TB{afades}[a]")
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
    silent = f"{BUILD}/cut.mp4"
    run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-f", "concat",
         "-safe", "0", "-i", listfile,
         "-c:v", "libx264", "-preset", "medium", "-crf", "19",
         "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", "-ar", "48000", silent])

    bed = build_music_bed(plan, f"{BUILD}/music_bed.wav")
    final = os.path.expanduser("~/Desktop/sightline-demo.mp4")
    run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-i", silent, "-i", bed,
         "-filter_complex",
         "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=0:"
         "normalize=0,alimiter=limit=0.95[a]",
         "-map", "0:v", "-map", "[a]",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-movflags", "+faststart", final])
    print(f"\n  FINAL {dur(final):.1f}s -> {final}")

if __name__ == "__main__":
    build()
