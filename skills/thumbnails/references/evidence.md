# What the evidence says

Weigh each claim by how it was learned, strongest first:

1. **Your own A/B results** on your audience, decided by watch time. Nothing else outranks them.
2. **Within-channel comparisons** of a channel's best thumbnails against its own others.
3. **Large cross-channel studies**, confounded by topic, promotion and survivorship.
4. **Practitioner experience.**
5. **Vendor "lift" numbers**, which rarely disclose a method.

A rule pooled across many channels can reverse inside one channel, so learn from your own tests
before borrowing anyone's rules.

## What the platform optimizes (YouTube Help)

- Test & Compare decides by watch-time share rather than click-through rate, so a thumbnail helps when
  it tells a viewer what the video is about. Up to three thumbnails (or titles, or pairs); variants
  that are too similar run longer; an inconclusive test keeps the first one uploaded; any arm under
  1280×720 drops every arm to 480p. (YouTube Help, answer 13861714)
- Many tests end without a clear winner; plan for ties.
- Recommendations weigh click-through, watch time and viewer satisfaction; clickbait shows up as high
  click-through with short viewing and falling impressions. (YouTube Help, answer 7628154)
- Changing an older video's thumbnail carries no penalty. (YouTube Help, answer 12340300)
- A thumbnail that implies something the video does not contain breaks policy. (YouTube Help,
  answer 9229980)
- Upload specification: 3840×2160 recommended, at least 1280×720, 16:9, up to 50 MB from a desktop
  and 2 MB from the phone app. (YouTube Help, answer 72431)

## Where it appears and how big

Feed layouts are A/B tested and drift, so re-measure when it matters. Roughly: desktop search about
500×281, home about three cards a row, the watch-page rail about 215×121, a phone full-bleed about
375×210. The duration pill is fixed-size, so it covers far more of the frame on the rail than in
search. TV is a large share of viewing for some audiences and favours clean, poster-like frames;
check the channel's device report before weighting any surface.

## Design features

Every one of these is contested; across the better data, features matter far less than the idea.

- **The idea.** Within one channel, the thumbnails that outperform differ in what they promise and
  how literally they show it, not in a repeatable design feature.
- **Faces** have no reliable overall effect. A face helps when the person is part of the promise or
  known to the audience; natural expressions beat exaggerated ones; more than a few people hurts.
- **Text.** Most strong thumbnails carry a few words; more text tends to go with fewer views, and the
  best covers repeat the title less. A number works when the number is the finding.
- **Complexity** has a sweet spot: too plain says nothing, too busy reads as noise, especially for
  tutorials.
- **Colour** is contrast with the feed and the neighbours, not a hue rule.
- **Developer and B2B audiences** respond to concrete artefacts (real UI, code, a named person, a
  stated payoff) over corporate cards, and they punish hype.
- **Series.** A light, consistent series signature helps returning viewers; the concept should still
  change every time.

## Legibility

- Light text on a dark ground reads slower than dark on light, most at small sizes; a bolder weight
  helps light-on-dark more (Dobres et al., studies of glance legibility, 2016-2017).
- At the 215 px rail, readable type needs roughly a tenth of the frame height per line on a 1280×720
  canvas, which caps the text at a few short words (derived from Legge and Bigelow, 2011, on print
  size and reading).
- WCAG's 4.5:1 applies to images of text: measure against the pixels behind the glyphs, which is what
  `thumb-gate` does for the marked hero.
- A shadow or a soft panel keeps text over a photo legible better than a thin outline.

## Judges and generated imagery

- Predicting A/B winners from the image alone is unsolved for people and for models; treat a judge's
  preference as one opinion.
- Models are good at consistency checks: given the transcript, they catch thumbnails that promise
  something the video does not contain. Compare pairs in both orders, and use a fresh evaluator rather
  than self-critique.
- Generated imagery wins only when it does not look generated; perceived artificiality costs trust.
  Typeset text and real marks deterministically, in HTML.
