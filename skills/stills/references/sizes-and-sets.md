# Sizes, carousels and documents

## Common sizes

Check the channel's current specification when a placement matters; these are starting points.

| Channel | Format | Size |
| --- | --- | --- |
| LinkedIn | single image | 1200×627 |
| LinkedIn, Instagram | square | 1080×1080 |
| LinkedIn, Instagram | portrait | 1080×1350 |
| Instagram, TikTok | story | 1080×1920 |
| X, link cards, blog headers | landscape | 1600×900 or 1200×675 |
| Display | medium rectangle | 300×250 |
| Display | leaderboard | 728×90 |
| Display | skyscraper | 160×600 |

"Various sizes" with no channel means the brand pack's formats, or the three LinkedIn sizes. The
small banners (728×90, 160×600) drop everything but the mark, one line and the next step.

## Carousels: a narrative, not one template six times

A carousel teaches one idea across a sequence; each slide earns the swipe. The failure mode is six
near-identical slides (same kicker, big headline, one accent word): clean and monotone.

1. **Cover**: the subject and its one-line value. The most designed slide.
2. **The problem**: the gap the reader already feels.
3. **How it works**: the mechanism as a real diagram (rendered by `data-viz` and placed on the slide).
4. **One capability per slide**, each with its own visual: a before and after, a real UI crop, a number.
5. **Proof**: one real outcome, if there is one.
6. **The next step.**

Vary the layout slide to slide (statement, diagram, before and after, number, screenshot) and keep
continuity with one accent and fixed margins. A slide number, if any, is a bare `02`, never a footer
strip. Author each slide as its own page at one size (1080×1350). Render one sample slide first and
name the arc and approach in a line; build the rest once it has been seen. Assemble the PNGs into one
PDF for a document carousel (`html2pdf` with one page per slide).

## Paged documents (one-pagers, booklets, brochures)

- The supplied copy decides the page count. Do not add a closing page, a call to action, a title, a
  URL or a logo to fill space. Copy marked final ships verbatim.
- Build every page from one shared page component with shared margins and baseline. Hold equal outer
  margins and bottom padding across the set, top-align repeated card titles, and reflow to remove
  one-word widows.
- Use supplied backgrounds, logos and icons at their original proportions and colour.
- For more than a few pages, render a cover and one content page for review before the rest.
- Export with `html2pdf.mjs` at the exact page size asked for, in inches: `--size 8.5x11in` (US
  letter), `--size 8.27x11.69in` (A4).

## Static decks

A static deck is a 16:9 sequence: a PDF plus one PNG per slide (`html2png --size 1920x1080` per
slide; `html2pdf --size 20x11.25in` for the set, which is 1920×1080 CSS px). Animated decks use the HyperFrames `slideshow`
skill. Batch work shows one sample slide, then numbered batches that wait for approval. Deleting a
slide renumbers the rest. A PNG or PDF cannot carry video: ship the video beside its slide.
