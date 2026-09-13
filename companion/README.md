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

Then open `http://<your-lan-ip>:8099/` on a phone on the same network and press
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

## Not built yet

The **What's happening right now?** button is the entry point for interactive
description, and it is deliberately here rather than on the television: Vega has
no app-level speech recognition (FRICTION-LOG FL-004), so a spoken question can
only ever begin on this device.
