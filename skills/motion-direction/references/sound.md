# Sound for motion

What sound does for a film and how to prove it without ears. The making (host tools for voice, music
and effects; the synth cues; `plan.json`; mixing, levels and mastering; `audio-lint`) is the `sound`
skill. This page is the direction: what to put where. Each point is a default to weigh unless it
names its evidence.

## Sound is the skeleton

- **One grid for picture and sound.** Every sounding event's time is named in the beat table or
  `timeline.js`, and both the composition and the sound plan read it, so they cannot drift. Mark
  sound events on the HyperFrames elements as you build (`data-sfx-intent`, `data-sfx-start`,
  `data-sfx-dur`); `sound/scripts/extract-edl.mjs` turns them into the cue list.
- **You cannot listen, so you measure.** Turn "sounds thin" into band levels and "out of sync" into
  onset offsets, fix the number, and report the number, never "sounds good". The person's ear decides.
- **Silence is a choice, never an accident.** A silent film reads unfinished unless the brief says
  silent.

## Tempo and whole bars

| Mood | Tempo |
| --- | --- |
| Cinematic, regal | 60-80 BPM |
| Smooth | 90-110 BPM |
| Kinetic: reels, sizzles, energetic launches | 115-128 BPM |

Fill whole bars: BPM = 240 × bars ÷ seconds, so the length times the tempo divided by 240 is a whole
number (15 s at 128 BPM is 8 bars; 14 s at 120 BPM is 7). A voiceover-led film takes the voice's
rhythm, with the music under it.

## The shape of a score cut to music

| When | What |
| --- | --- |
| Frame 0 | An impact, with an onset right at the start |
| The first bar | Hits on the hook's words |
| After the hook | The groove |
| The bar before the drop | The build: rolls tightening, a riser |
| The last half beat | A breath: thinned groove or near silence, bridged by a reverse swell that ends exactly on the downbeat |
| The drop | The biggest impact on the final card, often with a held chord |
| The end | A short fade |

**The drop is louder than the build.** *Check*: short-term loudness in the second after the drop
against the build's peak (`ffmpeg -af ebur128`); lower the riser if the build out-punches the drop.

## One sound for each event the eye follows

The sound matches the motion's physics:

| Picture | Sound |
| --- | --- |
| Stretch, rise, pull | An upward zip |
| Weight, a heavy landing | A falling thud |
| Whip pan | Noise swept across the stereo field, peaking on the cut |
| Slice | Bright noise falling fast |
| Pop, landing | A bloop or a pluck |
| Letters or items arriving | Short high blips |
| Typing, decoding | A tick chatter, quiet |
| Flood, a rush into a cut | Rising noise |
| A reveal | A designed hit, the biggest of its passage |

- **Pan follows the picture**: a mover's sound pans with its position; impacts stay centred.
- **Pitch follows the motion**: rising for up, in and zoom-in; falling for falls, weight and exits;
  sequences climb.
- **Align by the peak, not the start.** Start a whoosh or a swell early by its attack, so its peak
  lands on the event; when something passes the lens, compute the time from the geometry.
- **One family for small interface sounds**, so repeated actions sound like one instrument
  (`sound/scripts/synth-cue.mjs`); something bigger or specific (a signature sting, an exact-length
  riser) is generated with `generate_sound_effect`, and reused for every repeat of its action.
- **Generated effects can come back mis-shaped** (a riser that fades before its cut, a sting with no
  tail): check each one's envelope against its event before placing it.

## The cull

After placing effects, remove anything too loud, out of place, or not helping the viewer understand.
Without ears, run proxies:

| Proxy | Pass |
| --- | --- |
| Every cue traces to a named event that is visible on screen | All of them; cut the rest |
| Level by role | Structural hits (impacts, drops, landings) loud; decorative sounds (ticks, blips) far quieter |
| Density | Only a few designed effects starting at the same instant |
| Masking | Every impact still shows its own onset in the final mix |
| Balance | Lows not far above the mids (below) |

## Balance

- **Keep the lows (under ~250 Hz) within roughly 8 dB of the mids (~250 Hz-4 kHz).** A mix with lows
  far above its mids loses the mids on laptop and phone speakers. *Check*: per-band RMS with ffmpeg
  (`bandpass` then `astats`), and the waveform (`showwavespic`); the build into the drop should be
  visible on it. Default to weigh.
- **The voice leads.** Music and effects sit under it; `score.mjs` levels each voice line, keeps the
  bed under the voice and ducks it further under speech.

## Loudness

- **Master to -14 LUFS integrated with a true peak at or under -1 dBTP**, measured on the encoded
  file. This is the delivery target `audio-lint` checks (±1 LU). It matches a common streaming
  normalization level: Spotify normalizes to -14 LUFS and recommends masters at or under -1 dBTP
  (<https://support.spotify.com/us/artists/article/loudness-normalization/>). Loudness is measured
  per ITU-R BS.1770 (<https://www.itu.int/rec/R-REC-BS.1770>).
- **Do not re-master by hand.** `sound/scripts/master.mjs` measures input and result; if the master
  still misses, the mix is the problem.
- **A hit on frame 0 meets the encoder's first frame.** Check true peak on the encoded file, not the
  WAV, especially when the film opens on an impact.

## The sync check

- **Every listed hit has an audio onset within a few milliseconds of its time** (well under a frame).
  Run onset detection on the muxed audio (`film-breakdown/scripts/analyze-audio.mjs`) against the
  grid's hits and report the worst offset.
- **In a voiceover-led film, every copy onset lands within two frames of its word.**

## Voiceover-led sync

- **The words' start times are the sync spec.** `generate_voiceover` writes word timings beside each
  line; for a supplied voice, `transcribe_audio` gives them. Store them in the grid and key every copy
  change to its word.
- **The music sits under the voice** as one continuous bed; the picture keys to the voice and a
  handful of designed hits, which still land the big moments.

## A supplied track wins

The person's track outranks a generated score. Map its beats first (`analyze-audio.mjs --js`), then
fit the shots to its sections: tempo and grid origin, any edits where the tempo shifts, downbeats,
the strongest hits and where sections change. Supplied music must be theirs to use; ask when it is
not clear.
