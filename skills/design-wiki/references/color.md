# Colour

Which colours exist is the brand pack's call: `design.allowedColors`, `extendedPalette`,
`bannedColors` and the `--brand-color-*` properties in `tokens.css`, plus what `graphic-language.md`
says each one means. `brand-lint` fails a composition that uses anything else. This page is how to
use the palette well.

## Grounds

- **A ground is chosen for the piece and the surface**, from the grounds the pack allows: the page a
  figure sits on, the deck a slide joins, the feed a card appears in. Default to weigh.
- **Mode is a narrative decision in motion.** A dark ground can carry the problem and a light one the
  resolution; a single change of mode at the turn is a strong device, and for that reason easy to
  overuse. Pick the structure the argument needs (`motion-direction`). Default to weigh.
- **Avoid pure black and pure white as held grounds** unless the pack uses them; most packs ban them
  because they read as a default rather than a choice. A flash frame is a different case (a brand
  decision, declared).
- **Gradients belong to light, not decoration**: a light falling across a ground, a pool, a limb. A
  two-colour fill used to make a frame look busy is decoration. Default to weigh.

## Depth and surfaces

- **Build a ladder per mode.** From the pack's colours, list the ground, a raised surface, text,
  secondary text, connectors and hairlines for each mode, with their measured contrast; the sample
  brand's `graphic-language.md` has one. Raise contrast by stepping down the ladder, not by jumping
  to the accent: an accent-coloured border is a second accent. Default to weigh.
- **Elevation flips between modes.** On a dark ground a raised surface is lighter than the ground.
  On a light ground with no lighter colour left (pure white banned, or already used), the shell goes
  darker and the cards inside it return to the ground's tone. Default to weigh.
- **Text, data marks and chrome take separate tokens.** Secondary text is not the border colour, and
  a chart's axis or line needs more contrast than the card edge beside it. Default to weigh.
- **A dashed border loses weight against a solid one.** A faint dashed boundary disappears; give a
  dash a step more contrast than a solid line, and measure borders against their ground (3:1 for
  one that carries meaning). Default to weigh.
- **A line graphic behind copy gets a ground-colour fade** that is strongest behind the words, so the
  text reads without boxing it. A highlight chip on a dark ground is a low-opacity tint of the
  accent with light text, not a bright fill. Default to weigh.
- **An "off-palette" fill in a supplied source is often a token at low opacity.** Before declaring
  an exception, solve `alpha = (sampled - ground) / (token - ground)` per channel; if the three agree,
  the source used the token over the ground, and `rgba()` of the token reproduces it exactly.

## One accent, carrying meaning

- **One accent element per frame.** The accent marks the single thing that matters most: the key
  number, the active step, the new feature. A second bright colour competes for the eye. Default to
  weigh; most packs state it as a rule.
- **The accent means the same thing everywhere** in a set or a film. If it marks "the new thing" on
  one slide, it does not decorate a border on the next.
- **A shared element keeps its colour across a change.** When a frame's accent changes around an
  object that is carried from one frame to the next, give the object its own token so it stays
  identical.
- **Never introduce a colour without a reason.** Every colour on a frame answers "what does this
  mean?".

## Colour that encodes data or state

- **Categories and states use the extended palette, semantically**: chart series, pass and fail,
  healthy and warning. Keep the brand's primary colour as the anchor (the highlighted series, the
  primary state) and the tints for the rest.
- **Colour is never the only signal.** WCAG 2.1 SC 1.4.1: colour is not the only visual means of
  conveying information or distinguishing an element
  (<https://www.w3.org/WAI/WCAG21/Understanding/use-of-color.html>). Pair it with position, a label,
  a shape or a pattern. About 1 in 12 men have a colour vision deficiency, most often difficulty
  telling red from green (US National Eye Institute,
  <https://www.nei.nih.gov/learn-about-eye-health/eye-conditions-and-diseases/color-blindness>).
- **Status colours mean status.** Red, amber and green are reserved for fail, warn and pass where the
  pack has them; they are not accents.
- **Map sampled colours to tokens.** When you sample a reference's colours (`film-breakdown`, a
  screenshot), map each to the nearest brand token; never carry a reference's palette into the
  brand's work.

## Contrast

| What | Minimum | Evidence |
| --- | --- | --- |
| Normal text | 4.5:1 | WCAG 2.1 SC 1.4.3, <https://www.w3.org/TR/WCAG21/#contrast-minimum> |
| Large text (at least 18 pt, or 14 pt bold) | 3:1 | WCAG 2.1 SC 1.4.3 |
| Graphical objects a reader needs (a chart mark, a connector, an icon that carries meaning) | 3:1 against adjacent colours | WCAG 2.1 SC 1.4.11 |

- `brand-lint` measures text contrast (`contrast.wcag`), resolving `var()` through the tokens. It
  cannot see text drawn over an image or a video frame: check those on the render.
- **Contrast on a phone outdoors is worse than on your monitor.** Light type on a dark ground reads
  slower at small sizes; give small text more weight or size rather than relying on the ratio alone.
  Default to weigh.
- **A marker the colour of its ground disappears**, however correct its token. Look for it on the
  render (`visual-verify`).

## Flashes and light (motion)

- **No more than three flashes in any one second.** WCAG 2.1 SC 2.3.1 (Three Flashes or Below
  Threshold) applies to video as much as to pages
  (<https://www.w3.org/TR/WCAG21/#three-flashes-or-below-threshold>). A flash frame at a turn is a
  single event, not a strobe.
- **Glow and bloom are brand decisions**, declared in the film's `STYLE.md` when the pack allows them;
  a pale surface under an additive glow clips and floods its label, so a glowing card keeps its body
  and type drawn on top of the halo. Default to weigh.
