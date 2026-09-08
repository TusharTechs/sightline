# Sightline — Project Handoff

**Read this first.** Written 8 September 2026 at the end of day 1, for continuing
work on a different machine. Intended for both a human and an AI coding agent.

---

## 1. What this is

**Sightline** — a Fire TV (Vega OS) app that generates audio description in real
time for video that has none, and delivers it as a personal audio channel so a
blind viewer and a sighted viewer can watch the same thing together.

Built for the **Build, Ship, Shape: Amazon Developer Hackathon**.

- **Track:** Fire TV (Vega OS, React Native). Prize: $25,000 first place.
- **Mini-challenges targeted:** AWS Builder, Open Source (a project may win one
  track prize plus one mini-challenge).
- **Deadline:** 23 October 2026, 12:00 PDT (00:30 IST, 24 Oct). Treat 22 Oct as
  the real deadline — submit a day early.
- **Judging:** first two weeks of November. Winners announced at re:Invent.
- Devpost: https://amazonappdev2026.devpost.com/

---

## 2. Why this project, and why this track

Decisions already made and not worth relitigating without new information.

**Why Fire TV over Alexa+.** Both carry $25,000 first prizes. Alexa+ will attract
far more submissions because its rules permit a purely simulated experience, and
the organisers have said publicly that the Alexa+ track is "very much an ideation
project" — mockups are acceptable, so depth of engineering counts for less. Fire
TV has a real barrier (Vega SDK, RN for TV, focus management), which thins the
field, and the runtime is publicly available so "effectively leverages device
capabilities" can actually be demonstrated. Alexa+ for Builders is gated to
select partners, so an Alexa+ submission would never touch real Alexa+.

**Why this idea.** Fire TV's published priority categories are AI-enhanced
viewing, sports, fitness, family entertainment, multi-modal UX, and computer
vision. Sightline sits in **AI-enhanced viewing** and **multi-modal UX**.
Accessibility is *not* on the Fire TV priority list (it is on Ring's), so the
submission should **lead with AI-enhanced viewing and multi-modal UX**, with
accessibility as the use case that proves it — not the other way round.

**Content licensing shapes everything.** Demo videos "must not include third
party trademarks, or copyrighted music or other material unless the Entrant has
permission." This kills most Fire TV concepts. It does not affect Sightline,
whose entire premise is content that has no description: demo on Blender open
movies (Sintel, Big Buck Bunny, Tears of Steel — CC-BY, attribution required) and
original footage.

**Friction log is worth up to a 10% score bonus.** Amazon's internal review team
assesses friction-log entries and passes a recommended bonus to the judging
panel. See `FRICTION-LOG.md` — 11 entries already, all from real work. This is
first-class deliverable, not an afterthought.

---

## 3. Product definition

Three capabilities, in priority order:

1. **Generated description** for content with no description track. This is the
   core. Scene understanding → description text → speech → played over the video.
2. **Personal audio channel.** Description goes to one viewer (via a companion
   phone) while the room hears normal audio. Solves mixed-ability co-viewing.
3. **Interactive description.** Mid-scene questions — "who else is in the room?",
   "what is she wearing?" — answered from the frames. Impossible with a
   pre-recorded track; this is the LLM-native capability.

**Register is a product feature, not a quality dial.** A blind professional on
the ADP mailing list put it best: *"On a movie I want craft. On a training video
I want to know what's on the screen, and I'll take plain over beautiful every
time."* Build a register control, not just a verbosity slider.

**Do not optimise for voice beauty.** Research and user feedback both say
description quality and user control matter far more than TTS naturalness.

**Position carefully.** Never frame this as cheaper or faster than human
describers. ACB's published TTS guidelines say human-voiced description is
preferred and TTS should never be used "purely as a cost-saving measure" — and
professional describers read the list this project is engaging with. The
defensible framing, which is also true: description for content that has none and
never will. Where a professional track exists, play it and get out of the way.
Disclose synthetic voice in-product (ACB guidelines require it).

---

## 4. Architecture (settled, with the facts that forced each decision)

```
Fire TV app (Vega, React Native 0.83)
├── Video: react-native-w3cmedia, MSE mode, Shaka Player, HLS/DASH
├── Description audio: second AudioPlaybackStream via
│   @amazon-devices/keplerscript-audio-lib, AudioUsageType.USAGE_ACCESSIBILITY
│   (ducks media automatically), StreamDuckingPolicy SYSTEM or EXPLICIT
├── Controls: D-pad (no microphone available on Vega)
└── WebSocket to backend

Companion phone (web client, local network or via backend)
├── Private description audio  ─┐ both live here because Vega has neither
└── Voice questions (mic)      ─┘ a microphone nor per-stream audio routing

Backend (AWS)
├── Scene understanding (Bedrock), description generation
├── Speech synthesis (Polly)
└── Sends description audio + target playback timestamp so the phone
    schedules locally — removes network latency from A/V sync
```

**Why the phone carries the differentiators:** verified platform limits, not
preference. See §5.

---

## 5. Verified platform facts

Established by testing or by Amazon's own documentation/community answers. Do not
re-derive these.

| Fact | Consequence |
|---|---|
| `audioTracks`/`textTracks` never populate in **URL mode** (Amazon-confirmed known limitation) | Must use **MSE mode** with Shaka. Not flat MP4. |
| `keplerscript-audio-lib` provides `AudioPlaybackStreamBuilder`, `AudioUsageType.USAGE_ACCESSIBILITY` ("ducks most other audio"), `setDuckingPolicy` (SYSTEM/EXPLICIT), `duckVolume` | The core mechanic is natively supported |
| **No app-level speech-to-text on Vega.** Amazon-confirmed. Only the platform keyboard mic on a focused `TextInput`, or press-and-hold Alexa | Voice input must come from the companion phone |
| **No per-stream audio output routing.** Only whole-device HDMI↔Bluetooth switching | Private per-viewer audio must come from the companion phone |
| WebSockets supported; XHR with no CORS. `keplerscript-netmgr-lib` needs `com.amazon.network.service` + `com.amazon.network.privilege.net-info` (user-granted at runtime) | Companion-device link is straightforward |
| Media services must be declared in `manifest.toml` `[wants]` or playback **fails silently with no error** | Declare up front. See §7 for the list. |
| **No sample anywhere uses `keplerscript-audio-lib`** — not `vega-video-sample`, not `vega-audio-sample` (both use `react-native-w3cmedia`) | You are writing this from the API reference alone |
| VoiceView **cannot be enabled on the Vega Virtual Device** by any of the three documented methods | See FL-011. Open question in §10. |
| Native crash symbolication requires **Amazon-internal Midway auth** | Read ACR files as plain text instead — they contain `<minidump_stackwalk>` |
| `vega-video-sample` **crashes (SIGSEGV)** on the current VVD — two RCT-folly versions (0.72 + 0.83) in one process | Do not build on it. See §6. |

**The accessibility FAQ published for Vega Web Apps (WCAG/ARIA/aria-live) does
not apply to React Native for Vega.** RN uses accessibility props and
`AccessibilityInfo`. Don't chase ARIA.

**Sightline's own UI must be VoiceView-navigable.** A blind viewer has to turn
description on, change register, and ask a question. An audio-description app a
blind person can't operate is a fatal demo flaw. The FAQ's testing checklist is
the acceptance criteria.

---

## 6. Repo layout

```
sightline/
├── HANDOFF.md          ← this file
├── FRICTION-LOG.md     ← 11 entries. Keep adding. Worth up to 10% score bonus.
├── CLAUDE.md           ← generated by Amazon Devices Builder Tools (ADBT)
├── .adbt-config.json   ← ADBT project config
└── reference/          ← GITIGNORED (2.3GB). Recreate on the new machine.
    ├── sightlineprobe/            ← clean RN 0.83 Vega app. THE SEED. Works.
    ├── vega-video-sample/         ← reference only. CRASHES. Do not build on it.
    ├── vega-audio-sample/         ← reference only
    └── hello-world-fire-tv-react-native/  ← NOT Vega. Expo/Android TV. Ignore.
```

**Build Sightline from `sightlineprobe`**, not from `vega-video-sample`. The probe
is a scaffolded RN 0.83 app with three dependencies that builds, installs and runs
cleanly on the VVD. Port the W3C media player and Shaka setup across as code you
understand, rather than inheriting a dependency set that segfaults.

`CLAUDE.md` is Amazon-generated and 189 lines, including a directive to print a
welcome banner every session. Trim it if it becomes noise — the installer itself
says to customise it.

---

## 7. Setting up the new machine

Prerequisites: **macOS 10.15+ or Ubuntu 20.04+** (Vega requires one of these —
Windows can only do the Fire OS/Android path), Node.js 16+, Homebrew.

```bash
# 1. System dependencies
brew update && brew install binutils coreutils gawk findutils grep gnu-sed watchman jq lz4

# 2. Rosetta (Apple Silicon only)
softwareupdate --install-rosetta --agree-to-license

# 3. Vega SDK — interactive, 5–10 min, needs several GB free
curl -fsSL https://sdk-installer.vega.labcollab.net/get_vvm.sh | bash && source ~/vega/env
#    Accept defaults: component dir ~/vega/sdk, SDK version 0.24.9914,
#    Vega Studio into VS Code if you use it.

# 4. Verify
source ~/vega/env && vega --version     # expect: Active SDK 0.24.9914, CLI 1.3.4

# 5. Amazon Devices Builder Tools (MCP + Vega skills for Claude Code)
npx -y @amazon-devices/amazon-devices-buildertools-mcp@latest init-context
#    Choose Claude Code. Restart the session afterwards so the MCP server loads.
#    It writes MCP config to ~/.claude.json and CLAUDE.md into the project.

# 6. Reference samples (gitignored, so re-clone)
mkdir -p reference && cd reference
git clone --depth 1 https://github.com/AmazonAppDev/vega-video-sample.git
git clone --depth 1 https://github.com/AmazonAppDev/vega-audio-sample.git

# 7. Recreate the probe app
vega project generate -t helloWorld -n sightlineprobe --packageId com.sightline.probe -o .
#    NOTE: it writes files into -o directly, NOT into a subdirectory, and exits 1
#    on success (see FL-010). Create the directory first or move files after.

# 8. Build and run the probe
cd sightlineprobe && npm install && npm run build:debug
vega virtual-device start          # GUI window; may need to run detached
vega run-app build/aarch64-debug/sightlineprobe_aarch64.vpkg
```

**Gotchas learned the hard way:**

- `~/vega/env` is sourced in `~/.zshrc` but **not** in non-interactive shells.
  Prefix scripted commands with `source "$HOME/vega/env" &&`.
- The VVD dies if the process that launched it is reaped. Launch it with
  `nohup ... & disown`.
- VVD keyboard mapping: Select=`ENTER`, D-pad=arrows, Back=`ESC`, Home=`F1`,
  Menu=`F2`, Rewind/Play/FF=`F3`/`F4`/`F5`.
- `kepler` exists as a compatibility alias for `vega`.
- Run `vega project doctor` before every build. Read its **warnings**, not its
  summary — it reported "all critical checks passed" for an app that segfaults.
  Its "not a managed OS-version package" warning is the early signal for the
  dependency-version class of bug.
- **Keep dependencies SDK-tracked.** Use `vega project install <pkg>` so versions
  resolve against the target OS version. That is the likely root cause of the
  video sample's crash.

**Manifest — media + audio services to declare in `[wants]`** (silent failure
without them):

```toml
[[wants.service]]
id = "com.amazon.media.server"
[[wants.service]]
id = "com.amazon.audio.stream"
[[wants.service]]
id = "com.amazon.audio.control"
[[wants.service]]
id = "com.amazon.audio.system"
[[wants.service]]
id = "com.amazon.network.service"
[[wants.privilege]]
id = "com.amazon.devconf.privilege.accessibility"
[[needs.privilege]]
id = "com.amazon.network.privilege.net-info"
```

**Not needed on the new machine:** the `~/.kepler/acr_pyvenv` workaround from
FL-009 was only required because of corporate TLS inspection (Netskope). On a
clean network `acr-report` will bootstrap itself — though it still can't
symbolicate without Midway.

**Not needed at all:** the VVD's Settings → Amazon Account registration. Its own
tooltip says it's only for testing Amazon integrations (IAP, content launcher,
account login). Sightline uses none.

---

## 8. What's done

- Vega SDK 0.24.9914 + CLI 1.3.4 installed and verified
- Vega Virtual Device booting, reachable, developer mode on (`vvrp-tv-arm64`, OS 1.2)
- ADBT MCP server + 12 Vega skills wired into Claude Code
- `sightlineprobe` — clean RN 0.83 app building, installing, launching, stable
- `vega-video-sample` crash diagnosed and isolated to the sample (control test proves the platform is fine)
- Architecture settled against verified platform facts
- 11 friction-log entries
- AWS $150 credits requested (form closes 21 Oct 12:00 PT)
- Outreach live (see §9)

**Nothing of Sightline itself is built yet.** Day 1 was environment, validation
and research.

---

## 9. Outreach state

**ADP-List** (`ADP-List@acblists.org`) — ACB's Audio Description Project
discussion list, ~468 members who use and produce audio description. Posted a
thread revisiting a 2019 discussion (#3456) about delivering description through
headphones so the rest of the room hears normal audio. Two replies so far:

- A blind accessibility professional redirected the market: **workplace video** —
  onboarding, compliance modules, software walkthroughs — "it sits between a blind
  person and a paycheck." Asked to see actual clips rather than claims. **Promised
  to come back in a few weeks with clips, on both film and a workplace/software
  walkthrough.** This is a commitment; honour it.
- Another member requested a specific film (*Places In The Heart*, 1984, never
  described) and noted his sighted wife enjoys description because it catches
  things she missed and relieves her of describing. Both quotes are strong
  submission material.

**Saksham Trust** (Delhi, assistive technology) — emailed asking for remote
introductions to people who watch film/TV regularly. Paid, 30 minutes, remote.
Awaiting reply. **Score Foundation / Eyeway** (`scorefoundation@eyeway.org.in`) —
same ask, send if not already sent.

**r/Blind** — closed. Moderators confirmed product research and surveys are not
permitted. Do not post there. Do not DM members.

**Devpost Discord + Discussions** — two rules questions to ask (or confirm
answered): does a companion phone/second-screen component fit inside the Fire TV
track, and does CC-BY content with attribution satisfy the demo-video copyright
rule. Discord is where the developer advocates hang out; Devpost Discussions is
the formal, citable channel.

**Vega developer forum** (`community.amazondeveloper.com/c/vega/6`) — Q&A posted
about `USAGE_ACCESSIBILITY` streams, ducking, and whether the VVD emulates audio
focus. A follow-up was drafted adding the VoiceView findings. **FL-008 (the
sample crash) still needs filing in the Bug Reports section**, which is separate
from Q&A.

---

## 10. Open questions and risks

**The one that matters most.** Does the Vega Virtual Device emulate audio focus
and ducking faithfully, or is that only correct on physical hardware? The entire
demo is audio behaviour. If hardware is required, a Fire TV device running Vega OS
is needed within two to three weeks — start checking availability in India now,
in parallel with the forum reply.

**Unverified.** Whether `USAGE_ACCESSIBILITY` on an app-created stream ducks W3C
media playback automatically, or whether the media player must explicitly register
with platform audio focus. The accessibility FAQ hints at the latter: *"verify
your media player is properly integrated with the platform audio focus system."*

**Prior art to be honest about, not alarmed by.** AI audio description exists as
post-production tooling sold to publishers (Verbit, MediaScribe, Audible Sight,
ViddyScribe). Second-screen synced description shipped as Actiview, now Spectrum
Access — but only for titles where a described track exists and rights were
cleared. Interactive/user-controlled description has been studied ("Describe Now",
ACM DIS 2025, 20 BLV participants — cite it, it validates the premise). Per-viewer
audio for mixed-ability viewing is patented (US 11956497, US 10869073). **None of
this is a shipped consumer product on a TV.** The defensible claim is coverage:
second-screen delivery was solved; it only works for content someone paid to
describe.

**Business direction.** Entertainment on the TV is the wedge and the demo.
Workplace video is where the payer is (employers, compliance-driven). Say that in
the submission's impact section; don't build it.

---

## 11. What to do next, in order

1. **Get media playing in `sightlineprobe`** — `react-native-w3cmedia`, MSE mode,
   Shaka, a reachable HLS stream. Known-good: Apple's BipBop advanced example
   (`https://devstreaming-cdn.apple.com/videos/streaming/examples/img_bipbop_adv_example_fmp4/master.m3u8`),
   which has multiple audio renditions, and
   `https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8`. The Blender films are the
   demo content.
2. **The proof experiment** — open a second `AudioPlaybackStream` at
   `USAGE_ACCESSIBILITY` over the playing video and confirm the media ducks. This
   is Sightline in miniature. Everything else waits on it.
3. **File FL-008 in the Vega Bug Reports section** and post the forum follow-up.
4. **Resolve the hardware question.**
5. **Then** the description pipeline: frame sampling → Bedrock scene understanding
   → description text with register control → Polly → timed playback.
6. **Then** the companion phone client.
7. **Clips for the ADP list** — film *and* a software walkthrough. Promised.

**Not yet:** UI design, the companion phone, the AWS pipeline. All wasted if the
audio experiment fails.

---

## 12. Notes for the AI agent

- Verify before reporting. Several findings in `FRICTION-LOG.md` were corrected
  after first drafts overstated them. That log may go to Amazon — accuracy over
  volume.
- Read the ACR crash files as plain text; symbolication is unavailable.
- Prefer `search_documentation` / `read_document` from the ADBT MCP server over
  web search for Vega questions — the docs index isn't fully crawlable.
- The Vega skills (`amazon-devices-vega-*`) are installed and worth invoking:
  `media-player`, `app-manifest`, `focus-management`, `build-and-run`,
  `ui-components`, `best-practices`, `app-performance`.
- Log every friction point as it happens, in the required format: task attempted,
  steps taken, expected vs actual, severity, workaround, actionable suggestion.
  You cannot reconstruct these later.
