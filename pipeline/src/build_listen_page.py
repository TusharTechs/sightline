#!/usr/bin/env python3
"""
Turn a shape_test.py output directory into one page anyone can take the test on.

Sixteen separate audio files is a bad ask for a sighted person and a worse one
for a screen reader user, who would have to leave the page, find each download
and come back. One page with the clips inline is one link, no downloads, and it
scores itself so a participant gets their own result instead of only giving us
ours.

Accessibility is the point rather than a polish pass, since the people this is
for are screen reader users: real radio groups inside fieldsets with legends,
native audio controls rather than custom buttons, and the result announced
through a live region.

Usage:
    build_listen_page.py TEST_DIR --out web/listen
"""
import argparse, base64, json, os, shutil

PAGE = """<title>Can you hear what the machine hears?</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root {{ --bg:#fbfaf8; --fg:#1a1a1a; --mut:#5a5a5a; --line:#dcd8d2; --acc:#7a4a2a; --ok:#1d6b3f; --no:#9a2b2b; }}
  @media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
    --bg:#141414; --fg:#ededed; --mut:#a6a6a6; --line:#333; --acc:#d9a273; --ok:#6ed49b; --no:#e58b8b; }} }}
  :root[data-theme="dark"] {{
    --bg:#141414; --fg:#ededed; --mut:#a6a6a6; --line:#333; --acc:#d9a273; --ok:#6ed49b; --no:#e58b8b; }}
  body {{ background:var(--bg); color:var(--fg); margin:0;
    font:16px/1.6 Georgia,'Iowan Old Style',serif; }}
  main {{ max-width:42rem; margin:0 auto; padding:2rem 1.25rem 5rem; }}
  h1 {{ font-size:1.6rem; line-height:1.25; margin:0 0 .5rem; }}
  .sub {{ color:var(--mut); margin:0 0 2rem; }}
  .task {{ border-left:3px solid var(--acc); padding:.75rem 0 .75rem 1rem; margin:0 0 2rem; }}
  .clip {{ border:1px solid var(--line); border-radius:6px; padding:1rem; margin:0 0 1rem; }}
  legend {{ font-weight:bold; padding:0 .4rem; }}
  audio {{ width:100%; margin:.25rem 0 .75rem; }}
  .choices {{ display:flex; flex-wrap:wrap; gap:.5rem 1.5rem; }}
  label {{ display:flex; align-items:center; gap:.45rem; cursor:pointer; }}
  button {{ font:inherit; background:var(--acc); color:var(--bg); border:0;
    border-radius:5px; padding:.7rem 1.4rem; cursor:pointer; }}
  #out {{ margin-top:1.5rem; }}
  .res {{ border:1px solid var(--line); border-radius:6px; padding:1rem; }}
  .ok {{ color:var(--ok); }} .no {{ color:var(--no); }}
  table {{ border-collapse:collapse; width:100%; margin-top:1rem; }}
  th,td {{ text-align:left; padding:.35rem .5rem; border-bottom:1px solid var(--line); }}
  footer {{ margin-top:3rem; color:var(--mut); font-size:.9rem; }}
  a {{ color:var(--acc); }}
</style>
<main>
  <h1>Can you hear what the machine hears?</h1>
  <p class="sub">{n} clips, six seconds each. Half of them my code calls events.
  Half it calls the music. Can you tell which is which?</p>

  <div class="task">
    <p><strong>The task.</strong> Play each clip and decide: did
    <em>something arrive</em> &mdash; a thing happened &mdash; or did <em>the
    music build up</em>, with nothing actually happening?</p>
    <p>Listen to what comes <em>after</em> the loud moment, not just the loud
    moment itself. That is where the two differ.</p>
    <p>Every clip is level-matched, so loudness will not tell you the answer.
    Guess when you are unsure rather than skipping. It takes about ten minutes.</p>
  </div>

  <form id="quiz">
{items}
    <p><button type="submit">Score my answers</button></p>
  </form>
  <div id="out" role="status" aria-live="polite"></div>

  <footer>
    <p>Clips are from <em>Sintel</em>, &copy; Blender Foundation, licensed
    <a href="https://creativecommons.org/licenses/by/3.0/">CC&nbsp;BY&nbsp;3.0</a>.</p>
    <p>Nothing is collected. Your answers are scored in your browser and go
    nowhere.</p>
  </footer>
</main>
<script>
// The key is base64'd so that a casual look at the page does not spoil the
// test. That is all it is for; anyone who wants to read it can.
const KEY = JSON.parse(atob("{enc}"));
const form = document.getElementById('quiz');
const out = document.getElementById('out');
form.addEventListener('submit', e => {{
  e.preventDefault();
  const said = KEY.map((_, i) => {{
    const c = form.querySelector(`input[name="q${{i+1}}"]:checked`);
    return c ? c.value : null;
  }});
  const missing = said.map((v,i)=>v?null:i+1).filter(Boolean);
  if (missing.length) {{
    out.innerHTML = `<p class="res">Still unanswered: clip ${{missing.join(', ')}}.
      Please guess rather than leave one blank.</p>`;
    return;
  }}
  const right = said.filter((v,i)=>v===KEY[i]).length;
  const n = KEY.length;
  // One-sided binomial: how often would guessing do at least this well?
  const C=(a,b)=>{{let r=1;for(let i=0;i<b;i++)r=r*(a-i)/(i+1);return r;}};
  let p=0; for(let i=right;i<=n;i++) p+=C(n,i); p/=Math.pow(2,n);
  const verdict = p<0.05
    ? 'That is better than guessing. The difference the code makes is audible to you.'
    : 'That is about what guessing gets. On this evidence the difference is not audible to you.';
  const nice = s => s==='hit' ? 'arrived' : 'built up';
  const rows = said.map((v,i)=>{{
    const ok = v===KEY[i];
    return `<tr><td>${{i+1}}</td><td>${{nice(v)}}</td><td>${{nice(KEY[i])}}</td>
      <td class="${{ok?'ok':'no'}}">${{ok?'correct':'missed'}}</td></tr>`;
  }}).join('');
  out.innerHTML = `<div class="res">
    <p><strong>${{right}} out of ${{n}} correct.</strong></p>
    <p>Guessing alone scores this well or better ${{(p*100).toFixed(1)}}% of the time.
       ${{verdict}}</p>
    <table><caption class="sub">Clip by clip</caption>
      <tr><th>Clip</th><th>You said</th><th>Code said</th><th></th></tr>
      ${{rows}}</table>
    <p>If you would tell me your score, I would be glad to know &mdash; especially
       if it was low. A result that disagrees with the code is more useful to me
       than one that agrees.</p>
  </div>`;
  out.scrollIntoView({{behavior:'smooth', block:'start'}});
}});
</script>
"""

ITEM = """    <fieldset class="clip">
      <legend>Clip {n} of {total}</legend>
      <audio controls preload="none" src="clips/{f}">Your browser cannot play audio.</audio>
      <div class="choices">
        <label><input type="radio" name="q{n}" value="hit"> Something arrived</label>
        <label><input type="radio" name="q{n}" value="swell"> The music built up</label>
      </div>
    </fieldset>"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("test_dir", help="a directory produced by shape_test.py")
    p.add_argument("--out", required=True)
    a = p.parse_args()

    key = json.load(open(os.path.join(a.test_dir, "key.json")))
    clips = os.path.join(a.out, "clips")
    os.makedirs(clips, exist_ok=True)

    items, answers = [], []
    for i, k in enumerate(key, 1):
        name = f"clip-{i:02d}.mp3"
        shutil.copy(os.path.join(a.test_dir, k["file"]), os.path.join(clips, name))
        items.append(ITEM.format(n=i, total=len(key), f=name))
        answers.append(k["answer"])

    enc = base64.b64encode(json.dumps(answers).encode()).decode()
    html = PAGE.format(n=len(key), items="\n".join(items), enc=enc)
    with open(os.path.join(a.out, "index.html"), "w") as f:
        f.write(html)
    print(f"  {len(key)} clips -> {a.out}/index.html")


if __name__ == "__main__":
    main()
