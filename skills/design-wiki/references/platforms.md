# Platforms: sizes and specs

Starting points for where a piece will be seen. The brand pack's own `[[formats]]` in `brand.toml`
come first; a size the ask names exactly wins over both. Platforms change their specs often: every
row says when and where it was checked. Before a final whose placement matters (a paid ad, a
thumbnail test), re-check the platform's own page.

`html2png.mjs --size <W>x<H>` renders each size as its own layout; `artifact-contract.mjs --expect
<file>:<W>x<H>` proves the output matches.

## Checked on 2026-10-17 against the platform's own page

| Placement | Size and shape | Limits | Source |
| --- | --- | --- | --- |
| YouTube video | 16:9 standard on desktop; match the recording frame rate (24, 25, 30, 48, 50, 60); MP4, H.264 High, 4:2:0, AAC-LC at 48 kHz, fast start | | YouTube Help 1722171, <https://support.google.com/youtube/answer/1722171> |
| YouTube thumbnail | 16:9, 3840×2160 recommended, at least 640 wide (author at 1280×720 and render at 3×, `thumbnails`) | JPG or PNG; 2 MB from mobile, 50 MB from desktop | YouTube Help 72431, <https://support.google.com/youtube/answer/72431> |
| YouTube Shorts thumbnail | 9:16, 2160×3840 recommended, at least 640 high | 50 MB, desktop only | YouTube Help 72431 |
| YouTube Shorts | Vertical video, up to 3 minutes | | YouTube Help 10059070, <https://support.google.com/youtube/answer/10059070> |
| Link preview (Open Graph image) | At least 1200×630, as close to 1.91:1 as possible | Minimum 200×200; 600×315 or more for the large preview; 8 MB | Meta for Developers, <https://developers.facebook.com/docs/sharing/webmasters/images/> |
| LinkedIn single-image ad, horizontal | 1.91:1, 1200×628 recommended | Minimum 640×360; JPG, PNG or GIF; 5 MB | LinkedIn Help a426534, <https://www.linkedin.com/help/lms/answer/a426534> |
| LinkedIn single-image ad, square | 1:1, 1200×1200 recommended | Minimum 360×360 | LinkedIn Help a426534 |
| LinkedIn single-image ad, vertical | 4:5, 720×900 recommended | Minimum 360×640; serves on mobile only | LinkedIn Help a426534 |

## Not reachable from here on 2026-10-17: confirm before a final

These are the commonly published sizes; the platform pages could not be read when this was written.

| Placement | Commonly used | Where to confirm |
| --- | --- | --- |
| Instagram feed | 1080 wide; 4:5 portrait at 1080×1350, 1:1 at 1080×1080; ratios between 1.91:1 and 4:5 keep their resolution | Instagram Help Center (image sizes) |
| Instagram, Facebook and TikTok stories and reels | 9:16 at 1080×1920; captions, account name and buttons cover the bottom and the right edge | Each platform's ads help (safe-zone templates) |
| X image post or ad | 16:9 (1600×900 or 1200×675), 1:1 at 1200×1200, 1.91:1 at 1200×628 for ads | X Business help, creative ad specs |
| Email header | A 600 px wide content column is the long-standing convention | The email service in use |

## Motion defaults

| Need | Default | Notes |
| --- | --- | --- |
| Landscape film | 1920×1080, 30 fps | HyperFrames renders at 30 fps unless told (`--fps`); 60 doubles the render time |
| Vertical cut | 1080×1920 | Re-laid out from the same timeline and score, never cropped from 16:9 |
| Square cut | 1080×1080 | As above |
| A film made to match a reference | The reference's own rate (`--fps 30000/1001` style rational rates are kept) | `film-breakdown` |

Slides: 1920×1080 per slide; a static deck as a PDF at `20x11.25in` (`stills`, sizes and sets).

## Placement notes

- **Feeds autoplay muted.** A film that must work on a feed reads with the sound off: the message is
  on screen, not only in the voiceover.
- **Frame 0 is a poster.** Autoplay and paused players open on the first frame, so it carries
  content, not a blank ground (`video-score` flags a blank head as `frames.blank-poster`).
- **Thumbnails are replaced by the video on hover** in some players, so the film's opening should pay
  the thumbnail's promise off (`thumbnails`).
- **Previews crop.** A link card shows at several sizes and a grid may show a centre crop of a tall
  image: keep the subject in the middle and the text away from the edges.
- **Display banners** (300×250, 728×90, 160×600 and the like) are tiny: they carry the mark, one line
  and the next step, nothing else (`stills`). Ad networks publish their own accepted sizes.
