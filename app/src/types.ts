/** A single spoken description, positioned on the media timeline. */
export interface Cue {
  /** Media time (seconds) at which this becomes relevant. */
  t: number;
  /** Rank among all cues. Lower is more important. Fixed — never reordered
   *  by playback speed; speed changes how far down the list we get, not the
   *  order. */
  rank: number;
  /** Filename of the 16-bit 48kHz stereo PCM for this line. */
  pcm: string;
  /** The text, for on-screen display and debugging. */
  text: string;
  /** Rendered duration in seconds, measured host-side. */
  duration: number;
}

export type Mode = 'fit' | 'pause';

export interface Timeline {
  /** Fragmented MP4 the cues belong to. */
  media: string;
  mimeCodec: string;
  mode: Mode;
  /** Silences available for description, in media time. Only used in fit mode. */
  gaps: {start: number; end: number}[];
  cues: Cue[];
}
