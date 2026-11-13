"""What the canvas can ask the engine for, and the templates that combine it.

A capability is one kind of creative asset the design agent makes, routed by `media-production` to
the skill that owns it: how it is named on the canvas, how the lead reads the ask, the board its
sign-off uses, what it hands back, and what it can be made from. An asset on the canvas is one
capability's piece of work in one task.

A template is a set of capabilities wired together for a common job (a launch kit, a post turned
into social), placed on the canvas as one task: a slot per asset, each made from what the task
starts from or from the slots before it, and some signed off by the team before anything is made
from them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

#: What a task starts from: the files, link or notes someone brought.
MATERIAL = "material"
#: What an asset hands back, as the canvas tells pieces of work apart.
MEDIA = ("frames", "video", "image", "gif", "doc", "audio")
#: What a delivery of mixed files counts as: a film with its poster frame is a film. Working notes
#: (`text`) ride with what they arrive with; on their own they are no asset's work.
LEADING_MEDIA = ("video", "gif", "audio", "image", "doc", "text")


@dataclass(frozen=True)
class Capability:
    id: str
    title: str
    line: str
    #: How the lead reads the ask: "(What they want back: <asks>.)"
    asks: str
    #: The runtime skill that makes it (`skills/<skill>/SKILL.md`).
    skill: str
    #: The board kind its review goes up as (`canvas_publish_board`), or "" when it has none.
    review: str
    #: What it hands back.
    makes: str
    #: The kinds of finished file that belong to it when they arrive without its id.
    accepts: tuple[str, ...]
    #: What it can be made from: the material, or another asset's `makes`.
    takes: tuple[str, ...]


@dataclass(frozen=True)
class Slot:
    key: str
    kind: str
    title: str
    brief: str
    #: The slots it is made from; none means what the task starts from.
    sources: tuple[str, ...] = ()
    #: The team signs it off before anything is made from it.
    gate: bool = False
    #: What the person gets, in a few words, as a template's card lists it.
    gets: str = ""
    #: The shape of each piece its card draws ("16:9", "9:16", "1.91:1", "210:297" for a page): a
    #: set of sizes, or the same shape as many times as it makes (two thumbnails, a carousel).
    shape: tuple[str, ...] = ("16:9",)


@dataclass(frozen=True)
class Template:
    id: str
    title: str
    line: str
    #: What it starts from, in words.
    starts: str
    #: What it can start from: the material, or a finished asset's `makes`.
    starts_from: tuple[str, ...]
    slots: tuple[Slot, ...]


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "board",
        "Storyboard",
        "Pose frames to sign off before anything moves",
        "a storyboard (pose frames on one sheet)",
        "storyboard",
        "storyboard",
        "frames",
        ("image",),
        (MATERIAL, "doc"),
    ),
    Capability(
        "video",
        "Video",
        "An explainer, motion graphic or cut-down",
        "a video or animation",
        "hyperframes",
        "storyboard",
        "video",
        ("video",),
        (MATERIAL, "frames", "video", "image", "doc", "audio"),
    ),
    Capability(
        "film",
        "Launch film",
        "30 seconds to 3 minutes, built with helpers",
        "a launch film",
        "launch-film",
        "storyboard",
        "video",
        ("video",),
        (MATERIAL, "frames"),
    ),
    Capability(
        "brief",
        "Brief",
        "An episode's idea, who it is for, and what it may state",
        "a brief (an episode's idea, who it is for, its length and a ledger of what it may "
        "state, in words)",
        "episode-plan",
        "brief",
        "doc",
        ("doc",),
        (MATERIAL, "doc"),
    ),
    Capability(
        "plan",
        "Plan",
        "An episode's spine, chapters, beats and shots, in words",
        "a plan (an episode's spine, chapters, beats and shots, in words)",
        "episode-plan",
        "plan",
        "doc",
        ("doc",),
        (MATERIAL, "doc"),
    ),
    Capability(
        "thumbs",
        "Thumbnails",
        "An A/B set that reads at phone size",
        "thumbnails (an A/B set)",
        "thumbnails",
        "thumbnails",
        "image",
        ("image",),
        (MATERIAL, "video", "frames", "image"),
    ),
    Capability(
        "still",
        "Stills",
        "Social cards, ads, banners, a one-pager",
        "a still or ad set (image, banner, sizes, PDF)",
        "stills",
        "stills",
        "image",
        ("image", "doc"),
        (MATERIAL, "frames", "image", "video", "doc"),
    ),
    Capability(
        "deck",
        "Deck",
        "Slides, animated or static",
        "a deck (animated or static)",
        "stills",
        "layout",
        "doc",
        ("doc", "image", "video"),
        (MATERIAL, "image", "frames", "doc"),
    ),
    Capability(
        "chart",
        "Chart or diagram",
        "A stat card, chart, flow or architecture",
        "a chart or diagram",
        "data-viz",
        "",
        "image",
        ("image",),
        (MATERIAL, "doc"),
    ),
    Capability(
        "genimg",
        "Generated image",
        "Illustration, texture or hero art",
        "a generated image (illustration, texture, plate)",
        "image-generation",
        "",
        "image",
        ("image",),
        (MATERIAL, "frames", "image", "doc"),
    ),
    Capability(
        "edit",
        "Image edit",
        "Crop, cut-out, composite or resize",
        "an edited image (crop, cut-out, composite)",
        "image-ops",
        "",
        "image",
        ("image",),
        (MATERIAL, "image"),
    ),
    Capability(
        "gif",
        "GIF",
        "A short loop that stays small",
        "a GIF",
        "gif-edit",
        "",
        "gif",
        ("gif", "video"),
        (MATERIAL, "video", "image", "frames"),
    ),
    Capability(
        "looks",
        "Looks",
        "Two or three directions to pick one from",
        "looks: two or three directions rendered with start_looks for the team to pick from",
        "content-brief",
        "looks",
        "frames",
        ("image",),
        (MATERIAL, "image"),
    ),
    Capability(
        "sound",
        "Voice and music",
        "Voice-over, a music bed, effects",
        "voice, music or sound",
        "sound",
        "",
        "audio",
        ("audio", "video"),
        (MATERIAL, "video", "doc"),
    ),
    Capability(
        "captions",
        "Captions",
        "Captions on a talking-head clip",
        "captions on a talking-head video",
        "embedded-captions",
        "",
        "video",
        ("video",),
        (MATERIAL, "video"),
    ),
    Capability(
        "study",
        "Film study",
        "What makes a reference film work",
        "a study of a reference film",
        "film-breakdown",
        "",
        "doc",
        ("doc", "image"),
        (MATERIAL, "video"),
    ),
)

TEMPLATES: tuple[Template, ...] = (
    Template(
        "launch-kit",
        "Launch kit",
        "A teaser and everything around it",
        "A launch post, doc or notes",
        (MATERIAL, "doc"),
        (
            Slot(
                "board",
                "board",
                "Storyboard",
                "Three to five beats for a 15-second teaser.",
                gate=True,
                gets="a storyboard you sign off first",
            ),
            Slot(
                "teaser",
                "video",
                "Teaser",
                "15 seconds at 1920×1080, built from the approved storyboard.",
                ("board",),
                gets="15-second teaser",
            ),
            Slot(
                "thumbs",
                "thumbs",
                "Thumbnails",
                "Two arms, each a different bet, from the teaser's real frames.",
                ("teaser",),
                gets="2 thumbnails",
                shape=("16:9", "16:9"),
            ),
            Slot(
                "gif",
                "gif",
                "GIF",
                "A 6-second loop of the payoff, under 5 MB.",
                ("teaser",),
                gets="6-second GIF",
            ),
            Slot(
                "cards",
                "still",
                "Social cards",
                "LinkedIn 1200×627, X 1600×900 and square 1080×1080, in the storyboard's look.",
                ("board",),
                gets="3 social cards",
                shape=("1.91:1", "16:9", "1:1"),
            ),
        ),
    ),
    Template(
        "explainer",
        "Explainer",
        "A video with its thumbnails and a vertical short",
        "A post, doc or script",
        (MATERIAL, "doc"),
        (
            Slot(
                "board",
                "board",
                "Storyboard",
                "The argument as beats, one line of narration each.",
                gate=True,
                gets="a storyboard you sign off first",
            ),
            Slot(
                "video",
                "video",
                "Explainer",
                "60 to 90 seconds at 1920×1080, built from the approved storyboard.",
                ("board",),
                gets="60–90 second video",
            ),
            Slot(
                "thumbs",
                "thumbs",
                "Thumbnails",
                "Two arms for an A/B test.",
                ("video",),
                gets="2 thumbnails",
                shape=("16:9", "16:9"),
            ),
            Slot(
                "short",
                "video",
                "Vertical short",
                "The strongest 20 seconds at 1080×1920, laid out again for the phone, never cropped.",
                ("video",),
                gets="20-second vertical short",
                shape=("9:16",),
            ),
        ),
    ),
    Template(
        "episode",
        "Episode",
        "A long explainer in chapters, planned in words before any picture",
        "A post, doc, script or notes",
        (MATERIAL, "doc"),
        (
            Slot(
                "brief",
                "brief",
                "Brief",
                "The one idea, who it is for, how long it runs, and each fact it may state "
                "with the material's own words for it.",
                gate=True,
                gets="a brief you sign off first",
                shape=("210:297",),
            ),
            Slot(
                "plan",
                "plan",
                "Plan",
                "The spine and the chapters first, then each chapter's beats and shots, in words.",
                ("brief",),
                gate=True,
                gets="a plan you sign off before any picture",
                shape=("210:297",),
            ),
            Slot(
                "board",
                "board",
                "Storyboard",
                "One chapter posed to set the look, then a sheet of poses per chapter.",
                ("plan",),
                gate=True,
                gets="a storyboard you sign off",
            ),
            Slot(
                "video",
                "video",
                "Episode",
                "4 to 10 minutes at 1920×1080, built chapter by chapter from the approved boards.",
                ("board",),
                gets="4–10 minute episode",
            ),
            Slot(
                "short",
                "video",
                "Shorts",
                "One short cut from each chapter, laid out again for the phone.",
                ("video",),
                gets="a short per chapter",
                shape=("9:16",),
            ),
        ),
    ),
    Template(
        "post-to-social",
        "Post to social",
        "Cards, a carousel and a stat from one post",
        "A blog post or article",
        (MATERIAL, "doc"),
        (
            Slot(
                "art",
                "genimg",
                "Hero art",
                "One illustration of the post's idea, no words or logos.",
                gets="Hero art",
            ),
            Slot(
                "cards",
                "still",
                "Social cards",
                "The post's headline over the art: LinkedIn, X and square.",
                ("art",),
                gets="3 social cards",
                shape=("1.91:1", "16:9", "1:1"),
            ),
            Slot(
                "carousel",
                "still",
                "Carousel",
                "Five 1080×1350 slides, one point each.",
                gets="5-slide carousel",
                shape=("4:5", "4:5", "4:5"),
            ),
            Slot(
                "stat",
                "chart",
                "Stat card",
                "The post's most telling number.",
                gets="Stat card",
                shape=("1:1",),
            ),
        ),
    ),
    Template(
        "ad-set",
        "Ad set",
        "Pick a look, then every size and a moving version",
        "A product page or brief",
        (MATERIAL, "image"),
        (
            Slot(
                "looks",
                "looks",
                "Looks",
                "Three directions; the team picks one.",
                gate=True,
                gets="three looks you pick one from first",
                shape=("1:1",),
            ),
            Slot(
                "ads",
                "still",
                "Ads",
                "The picked look at 1080×1080, 1080×1350, 1200×627 and 300×250.",
                ("looks",),
                gets="Ads in 4 sizes",
                shape=("1:1", "4:5", "1.91:1", "6:5"),
            ),
            Slot(
                "motion",
                "gif",
                "Animated ad",
                "A 4-second loop of the square ad, under 1 MB.",
                ("ads",),
                gets="4-second animated ad",
                shape=("1:1",),
            ),
        ),
    ),
    Template(
        "pitch",
        "Pitch pack",
        "Charts, a deck and a one-pager",
        "Notes, a doc or a spreadsheet",
        (MATERIAL, "doc"),
        (
            Slot(
                "charts",
                "chart",
                "Charts",
                "The two or three numbers the pitch rests on.",
                gets="2–3 charts",
                shape=("16:9", "16:9"),
            ),
            Slot(
                "deck",
                "deck",
                "Deck",
                "Eight to ten 16:9 slides as a PDF, using the charts.",
                ("charts",),
                gets="8–10 slide deck",
                shape=("16:9", "16:9"),
            ),
            Slot(
                "onepager",
                "still",
                "One-pager",
                "A one-page PDF in the deck's look.",
                ("deck",),
                gets="One-pager",
                shape=("210:297",),
            ),
        ),
    ),
    Template(
        "social-pack",
        "Social pack",
        "Thumbnails, a GIF, a short and cards for a finished video",
        "A finished video on the canvas",
        ("video",),
        (
            Slot(
                "thumbs",
                "thumbs",
                "Thumbnails",
                "Two arms from the video's real frames.",
                gets="2 thumbnails",
                shape=("16:9", "16:9"),
            ),
            Slot("gif", "gif", "GIF", "A 6-second loop of the payoff.", gets="6-second GIF"),
            Slot(
                "short",
                "video",
                "Vertical short",
                "1080×1920, laid out again for the phone.",
                gets="Vertical short",
                shape=("9:16",),
            ),
            Slot(
                "cards",
                "still",
                "Social cards",
                "LinkedIn, X and square, in the video's look.",
                gets="3 social cards",
                shape=("1.91:1", "16:9", "1:1"),
            ),
        ),
    ),
    Template(
        "talk",
        "Talk to clips",
        "A captioned clip, thumbnails and quote cards",
        "A talk recording",
        (MATERIAL, "video"),
        (
            Slot(
                "clip",
                "captions",
                "Captioned clip",
                "The talk's strongest minute, captioned.",
                gets="1-minute captioned clip",
            ),
            Slot(
                "thumbs",
                "thumbs",
                "Thumbnails",
                "Two arms with the speaker's real frame.",
                ("clip",),
                gets="2 thumbnails",
                shape=("16:9", "16:9"),
            ),
            Slot(
                "quotes",
                "still",
                "Quote cards",
                "Three quotes, word for word, at 1080×1350.",
                gets="3 quote cards",
                shape=("4:5", "4:5", "4:5"),
            ),
        ),
    ),
)

_CAPABILITY = {c.id: c for c in CAPABILITIES}
_TEMPLATE = {t.id: t for t in TEMPLATES}
#: The capability a board stands for when it arrives without an asset.
BOARD_CAPABILITY: Mapping[str, str] = {
    "storyboard": "board",
    "thumbnails": "thumbs",
    "stills": "still",
    "layout": "still",
    "looks": "looks",
    "plan": "plan",
    "brief": "brief",
}
#: The capability finished files stand for when they arrive without an asset.
MEDIA_CAPABILITY: Mapping[str, str] = {
    "video": "video",
    "gif": "gif",
    "image": "still",
    "doc": "still",
    "audio": "sound",
}


def capability(kind: str) -> Capability | None:
    return _CAPABILITY.get(kind)


def template(template_id: str) -> Template | None:
    return _TEMPLATE.get(template_id)


def media_of(mime: str, name: str = "") -> str:
    """What kind of finished file this is, the way assets accept them. Plain text (notes, a beat
    sheet, data) is `text`, which no asset makes."""
    mime = mime.lower()
    if mime == "image/gif" or name.lower().endswith(".gif"):
        return "gif"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("text/") or mime == "application/json":
        return "text"
    return "doc"


def ordered(slots: Sequence[Slot]) -> bool:
    """Every slot is made only from slots listed before it, and each key is used once."""
    seen: set[str] = set()
    for slot in slots:
        if slot.key in seen or any(s not in seen for s in slot.sources):
            return False
        seen.add(slot.key)
    return True


def catalog_view() -> dict[str, Any]:
    return {
        "capabilities": [asdict(c) for c in CAPABILITIES],
        "templates": [asdict(t) for t in TEMPLATES],
    }
