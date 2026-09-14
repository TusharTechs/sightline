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
  .ask {{ margin:.25rem 0 .5rem; }}
  textarea {{ width:100%; font:inherit; padding:.5rem; border:1px solid var(--line);
    border-radius:5px; background:var(--bg); color:var(--fg); box-sizing:border-box; }}
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
  <p class="sub">{n} clips, six seconds each. Most of them my code calls either
  an event or the music, and for those the question is which. A few it could
  not call at all, and for those the question is different: what would you
  want said?</p>

  <div class="task">
    <p><strong>The task.</strong> Play each clip and decide: did
    <em>something arrive</em> &mdash; a thing happened &mdash; or did <em>the
    music build up</em>, with nothing actually happening?</p>
    <p>Listen to what comes <em>after</em> the loud moment, not just the loud
    moment itself. That is where the two differ.</p>
    <p>Every clip is level-matched, so loudness will not tell you the answer.
    If you genuinely cannot tell, say so &mdash; that is an answer, not a
    failure, and it is more useful to me than a guess. It takes about ten
    minutes.</p>
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
// Which clips are the same audio played twice, by index.
const TWIN = JSON.parse(atob("{twins}"));
const form = document.getElementById('quiz');
const out = document.getElementById('out');
form.addEventListener('submit', e => {{
  e.preventDefault();
  const said = KEY.map((k, i) => {{
    if (k === 'unsure') {{
      const t = form.querySelector(`textarea[name="q${{i+1}}"]`);
      return t ? t.value.trim() : '';
    }}
    const c = form.querySelector(`input[name="q${{i+1}}"]:checked`);
    return c ? c.value : null;
  }});
  // Probes may be left blank. "Nothing" is a real answer to what should be said.
  const missing = said.map((v,i)=>(KEY[i]==='unsure'||v)?null:i+1).filter(Boolean);
  if (missing.length) {{
    out.innerHTML = `<p class="res">Still unanswered: clip ${{missing.join(', ')}}.
      "I could not tell" counts as an answer.</p>`;
    return;
  }}
  // Probes are clips the code itself could not call. They are not scored.
  const scored = KEY.map((k,i)=>i).filter(i => KEY[i] !== 'unsure');
  const decided = scored.filter(i => said[i] !== 'unsure');
  const right = decided.filter(i => said[i]===KEY[i]).length;
  const n = decided.length;
  const ducked = scored.length - decided.length;
  const probes = KEY.map((k,i)=>i).filter(i => KEY[i] === 'unsure');
  if (n === 0) {{
    out.innerHTML = `<p class="res">You could not tell on any of them. That is a
      real result and I would genuinely like to know it.</p>`;
    return;
  }}
  // One-sided binomial: how often would guessing do at least this well?
  const C=(a,b)=>{{let r=1;for(let i=0;i<b;i++)r=r*(a-i)/(i+1);return r;}};
  let p=0; for(let i=right;i<=n;i++) p+=C(n,i); p/=Math.pow(2,n);
  const verdict = p<0.05
    ? 'That is better than guessing. The difference the code makes is audible to you.'
    : 'That is about what guessing gets. On this evidence the difference is not audible to you.';
  const nice = s => s==='hit' ? 'arrived' : s==='swell' ? 'built up' : 'could not tell';
  const rows = said.map((v,i)=>{{
    let note, cls='';
    if (KEY[i]==='unsure') {{ note='not scored &mdash; the code could not call this one either'; }}
    else if (v==='unsure') {{ note='not scored'; }}
    else {{ const ok = v===KEY[i]; cls = ok?'ok':'no'; note = ok?'correct':'missed'; }}
    return `<tr><td>${{i+1}}</td><td>${{nice(v)}}</td><td>${{nice(KEY[i])}}</td>
      <td class="${{cls}}">${{note}}</td></tr>`;
  }}).join('');
  out.innerHTML = `<div class="res">
    <p><strong>${{right}} out of ${{n}} correct</strong>, on the ${{n}} you called.</p>
    <p>Guessing alone scores this well or better ${{(p*100).toFixed(1)}}% of the time.
       ${{verdict}}</p>
    ${{ducked ? `<p>You could not tell on ${{ducked}} more. That is not counted
       against you, and it is worth knowing.</p>` : ''}}
    ${{(() => {{
      const pairs = TWIN.map((t,i)=>t?[t-1,i]:null).filter(Boolean);
      if (!pairs.length) return '';
      const same = pairs.filter(([x,y])=>said[x]===said[y]).length;
      return `<p>${{pairs.length}} of the clips were the same audio played
        twice, in different places. You gave the same answer both times on
        ${{same}} of ${{pairs.length}}. That is the fair yardstick: a machine that
        changes its mind is only unreliable if it does so more often than a
        listener does.</p>`;
    }})()}}
    ${{probes.length ? `<p>${{probes.length}} of the clips were ones my own code
       could not call. They are not scored, and they were not the same
       question. What you would want said there:</p>
       <ul>${{probes.map(i=>`<li>Clip ${{i+1}}: ${{said[i]
          ? said[i].replace(/[<>&]/g, c=>({{'<':'&lt;','>':'&gt;','&':'&amp;'}}[c]))
          : '<em>nothing</em>'}}</li>`).join('')}}</ul>
       <p>Those answers are the most useful thing on this page and they are
       also the part I cannot score. Copy them to me if you are willing.</p>` : ''}}
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

PROBE = """    <fieldset class="clip">
      <legend>Clip {n} of {total}</legend>
      <audio controls preload="none" src="clips/{f}">Your browser cannot play audio.</audio>
      <p class="ask"><label for="t{n}">My code could not call this one. So
      rather than asking which it is: <strong>what would you want said here,
      if anything?</strong></label></p>
      <textarea id="t{n}" name="q{n}" rows="3"
        placeholder="Nothing, if nothing is what you would want."></textarea>
    </fieldset>"""

ITEM = """    <fieldset class="clip">
      <legend>Clip {n} of {total}</legend>
      <audio controls preload="none" src="clips/{f}">Your browser cannot play audio.</audio>
      <div class="choices">
        <label><input type="radio" name="q{n}" value="hit"> Something arrived</label>
        <label><input type="radio" name="q{n}" value="swell"> The music built up</label>
        <label><input type="radio" name="q{n}" value="unsure"> I could not tell</label>
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
        tmpl = PROBE if k["answer"] == "unsure" else ITEM
        items.append(tmpl.format(n=i, total=len(key), f=name))
        answers.append(k["answer"])

    enc = base64.b64encode(json.dumps(answers).encode()).decode()
    twins = base64.b64encode(
        json.dumps([k.get("twin") for k in key]).encode()).decode()
    html = PAGE.format(n=len(key), items="\n".join(items), enc=enc, twins=twins)
    with open(os.path.join(a.out, "index.html"), "w") as f:
        f.write(html)
    print(f"  {len(key)} clips -> {a.out}/index.html")


if __name__ == "__main__":
    main()
