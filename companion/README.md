# Companion channel

Solves co-viewing: a blind viewer and a sighted viewer watch the same thing
together, and only one of them wants description.

- **Solo** — description plays on the Fire TV's `USAGE_ACCESSIBILITY` stream and
  the platform ducks the film under it.
- **Co-viewing** — the room hears the film untouched. Description goes only to
  the phone. The television plays nothing extra and does not duck.

That is an inversion of the audio design, not a volume setting, which is why it
is a mode on the device rather than a slider.

## Running it

```bash
SIGHTLINE_BUNDLE=/tmp/sightline-serve python3 companion/server.py
```

Then open `http://<your-lan-ip>:8190/` on a phone on the same network and press
**Start listening**. On the television remote, **Down** toggles between solo and
co-viewing.

## How the sync works

The Fire TV posts its playhead to `/position` a few times a second. The phone
polls `/state` and interpolates between reports, so description does not arrive
in steps. Reporting is fire-and-forget — a missed update costs nothing, and
blocking playback on a network round trip would be far worse than a slightly
stale reading.

The television never listens on a socket. Description generation already needs a
service to live in, so the phone talks to that instead.

## Why the phone page looks the way it does

Its entire audience is blind. Large touch targets, a single primary action,
semantic landmarks, and an `aria-live` region that announces state changes.
Audio is unlocked by the Start gesture because mobile browsers require one.

## Interactive description

Ask about the moment you are on. By voice where the browser supports it, or from
preset questions, which are also faster than speaking for the common cases.

This is on the phone rather than the television for a hard reason: Vega has no
app-level speech recognition (FRICTION-LOG FL-004), so a spoken question can
only ever begin on this device. Building the companion channel was the
prerequisite for it existing at all.

It is also the thing a pre-recorded description track structurally cannot do.
Every batch tool decides in advance what is worth saying. Only something running
at playback time can answer a question about the frame in front of you — and
only because the viewer chose the moment.

Two behaviours that matter more than they look:

- **It answers the question and stops.** A second description is not an answer;
  the viewer asked because the description did not cover it.
- **It admits what it cannot see.** Real replies from the trailer include *"I
  can't be sure it's her"* and *"No room is shown — just the title card on
  black."* For someone who cannot check, a confident wrong answer is far worse
  than an admission.

**Known cost:** about 7 seconds from question to answer. Acceptable when the
viewer has chosen to interrupt, but it should be faster, and shaving it must not
be paid for with worse answers.
