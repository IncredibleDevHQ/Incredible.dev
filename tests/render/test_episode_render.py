"""An episode's film on the designer's computer: a picture built to the contract lints and is
posed at the end of each of its lines, and the film's page (the plan's first chapter, a spoken
take, its pictures) renders at the length its clock gives.

    uv run design-agent sandbox build
    uv run pytest -q -m render tests/render/test_episode_render.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from design_agent.episode import derive, film, picture, sketch, timeline, units
from design_agent.episode import plan as plans
from tests.render.test_gates_render import GSAP, IMAGE, ROOT, _image_available
from tests.render.test_render_smoke import run

pytestmark = [
    pytest.mark.render,
    pytest.mark.skipif(
        not _image_available(), reason=f"docker or the {IMAGE} image is unavailable"
    ),
]

SCRIPT = json.loads(
    (ROOT / "src/design_agent/surfaces/web/demo_episode.json").read_text(encoding="utf8")
)


def test_a_picture_is_posed_and_the_film_renders_to_its_clock(tmp_path: Path) -> None:
    full = derive.full(plans.merged(SCRIPT["plan"], SCRIPT["labels"]))
    full["chapters"] = full["chapters"][:1]
    full["marks"] = [m for m in full["marks"] if m["mark"] != "chapter-card"]
    chapter = full["chapters"][0]
    lines = [f for b in chapter["beats"] for f in b["frames"]]
    found = units.units(full)
    assert found, "the first chapter shows a picture"
    pictures = {u["id"]: sketch.built(picture.brief(u, full)) for u in found}
    take = {
        "id": "tk_1",
        "chapter": chapter["id"],
        "frame": "",
        "seconds": 2.0 * len(lines),
        "marks": [{"frame": f["id"], "t": 2.0 * i} for i, f in enumerate(lines)],
    }
    clock = timeline.schedule(full, [take])

    # one picture alone, as the studio poses it
    unit = found[0]
    comp = picture.composition_id(unit["id"])
    own = picture.clock(unit, timeline.schedule(full))
    pose = tmp_path / "pose"
    (pose / picture.FOLDER).mkdir(parents=True)
    (pose / "index.html").write_text(picture.stage(unit, own))
    (pose / picture.FOLDER / f"{comp}.html").write_text(picture.dressed(pictures[unit["id"]], own))
    at = ",".join(str(t) for t in picture.still_times(own).values())

    project = tmp_path / "film"
    for path, text in film.project(
        full,
        clock,
        found,
        pictures,
        takes={"tk_1": {"video": "takes/tk_1.mp4", "audio": "takes/tk_1.m4a"}},
    ).items():
        (project / path).parent.mkdir(parents=True, exist_ok=True)
        (project / path).write_text(text)
    (project / "takes").mkdir()

    proc = run(
        tmp_path,
        f"set -e; cp {GSAP} pose/ && cp {GSAP} film/ "
        "&& hyperframes check pose "
        f"&& hyperframes snapshot pose --at {at} --no-end --keep -o stills --describe false "
        f"&& ffmpeg -v error -f lavfi -i testsrc2=size=640x360:rate=30 -f lavfi "
        f"-i sine=frequency=330:sample_rate=48000 -t {take['seconds']} -c:v libx264 -g 15 "
        "-pix_fmt yuv420p -c:a aac film/takes/tk_1.mp4 "
        "&& ffmpeg -v error -i film/takes/tk_1.mp4 -vn -c:a copy film/takes/tk_1.m4a "
        "&& hyperframes lint film "
        "&& hyperframes render film --quality draft --fps 30 --output film.mp4 --quiet "
        "&& ffprobe -v error -show_entries format=duration:stream=codec_type -of json film.mp4",
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    stills = sorted((tmp_path / "stills").glob("at-*.png"))
    assert len(stills) == len(unit["frames"]) and all(s.stat().st_size > 2_000 for s in stills)
    probe = json.loads(proc.stdout[proc.stdout.rindex('{\n    "programs"') :])
    assert float(probe["format"]["duration"]) == pytest.approx(clock["total"], abs=0.1)
    assert {s["codec_type"] for s in probe["streams"]} == {"video", "audio"}


@pytest.mark.parametrize("dark", [False, True])
def test_catalog_pictures_are_visible_and_change_on_their_cues(tmp_path: Path, dark: bool) -> None:
    from PIL import Image, ImageChops, ImageStat

    look = picture.Look(
        palette={
            **picture.PALETTE,
            **(
                {
                    "ground": "#101a2a",
                    "panel": "#192638",
                    "ink": "#edf2ff",
                    "accent": "#ffbd6a",
                    "accent_ink": "#101a2a",
                }
                if dark
                else {
                    "ground": "#faf5e9",
                    "panel": "#fffdf7",
                    "ink": "#262e2b",
                    "accent": "#006d61",
                    "accent_ink": "#ffffff",
                }
            ),
        }
    )
    cases = {
        "detail-card": (
            "stacked",
            [
                {"words": "Receipt"},
                {"words": "Approved", "what": "Status", "state": "active"},
                {"words": "Visa", "what": "Method"},
            ],
        ),
        "stepper": (
            "horizontal",
            [{"words": "Submitted"}, {"words": "Authorized"}, {"words": "Captured"}],
        ),
        "sequence-diagram": (
            "vertical-lanes",
            [
                {"words": "Order", "from": "Customer", "to": "Shop"},
                {"words": "Authorize", "from": "Shop", "to": "Bank"},
                {"words": "Decision", "from": "Bank", "to": "Shop"},
            ],
        ),
        "bar-chart": (
            "vertical",
            [
                {"words": "January", "value": 32, "unit": "orders"},
                {"words": "February", "value": 48, "unit": "orders"},
                {"words": "March", "value": 40, "unit": "orders"},
            ],
        ),
    }
    for name, (variant, objects) in cases.items():
        folder = tmp_path / name
        (folder / picture.FOLDER).mkdir(parents=True)
        unit = {"id": "a", "canvas": [800, 450]}
        comp = picture.composition_id("a")
        cues = [{"key": f"a/{i}", "object": f"o{i}"} for i in range(3)]
        own = {"seconds": 2.2, "lines": {"a": [0, 2.2]}, "cues": {"a/0": 0, "a/1": 0.7, "a/2": 1.4}}
        brief = {
            "composition_id": comp,
            "canvas": {"width": 800, "height": 450},
            "keep_clear": None,
            "visual": {"component": name, "variant": variant},
            "look": look.tokens(),
            "lines": [
                {
                    "frame": "a",
                    "objects": [{**obj, "id": f"o{i}"} for i, obj in enumerate(objects)],
                    "cues": cues,
                }
            ],
        }
        (folder / "index.html").write_text(picture.stage(unit, own, ground=look.palette["ground"]))
        (folder / picture.FOLDER / f"{comp}.html").write_text(
            picture.dressed(sketch.built(brief), own, look)
        )
    result = run(
        tmp_path,
        f"""set -e
for scene in detail-card stepper sequence-diagram bar-chart; do
  cd "$scene"
  cp {GSAP} .
  hyperframes render . --quality draft --fps 24 --output sample.mp4 --quiet
  for stamp in 0.5 1.2 1.95; do
    ffmpeg -nostdin -v error -ss "$stamp" -i sample.mp4 -frames:v 1 -y "$stamp.png"
  done
  cd ..
done""",
    )
    assert result.returncode == 0, result.stderr[-2000:] + result.stdout[-2000:]
    for name in cases:
        frames = [Image.open(tmp_path / name / f"{t}.png").convert("RGB") for t in (0.5, 1.2, 1.95)]
        for a, b in zip(frames, frames[1:], strict=False):
            assert max(ImageStat.Stat(ImageChops.difference(a, b)).mean) > 0.12, name
        assert max(ImageStat.Stat(frames[-1]).stddev) > 12, name


def test_presenter_window_interpolates_in_encoded_frames(tmp_path: Path) -> None:
    from PIL import Image

    full = derive.full(plans.merged(SCRIPT["plan"], SCRIPT["labels"]))
    chapter = full["chapters"][0]
    full["chapters"], full["marks"] = [chapter], []
    lines = [f for b in chapter["beats"] for f in b["frames"]]
    for f, layout in zip(lines, ("full-frame", "avatar-bubble", "corner-window"), strict=True):
        f.update(layout=layout, presence="person" if layout == "full-frame" else "both")
    take = {
        "id": "camera",
        "chapter": chapter["id"],
        "seconds": 3,
        "marks": [{"frame": f["id"], "t": i} for i, f in enumerate(lines)],
    }
    clock = timeline.schedule(full, [take])
    project = tmp_path / "film"
    project.mkdir()
    (project / "index.html").write_text(
        film.project(full, clock, [], {}, takes={"camera": {"video": "camera.mp4"}})["index.html"]
    )
    times = (0.9, 1.2, 1.6, 2.2, 2.6)
    extract = " && ".join(
        f"ffmpeg -v error -ss {t} -i out.mp4 -frames:v 1 -vf scale=480:270 {i}.png"
        for i, t in enumerate(times)
    )
    result = run(
        tmp_path,
        f"cp {GSAP} film/ && ffmpeg -v error -f lavfi -i color=red:s=320x180:r=30 -t 3 -c:v libx264 -pix_fmt yuv420p film/camera.mp4 && hyperframes render film --quality draft --fps 30 --output out.mp4 --quiet && {extract}",
    )
    assert result.returncode == 0, result.stderr[-1000:]
    boxes = []
    for i in range(len(times)):
        with Image.open(tmp_path / f"{i}.png") as im:
            mask = im.convert("RGB").split()[1].point(lambda g: 255 if g < 40 else 0)
            box = mask.getbbox()
            assert box
            boxes.append(box)
            if i == 2:
                assert mask.getpixel((box[0] + 1, box[1] + 1)) == 0
                assert mask.getpixel(((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)) == 255
    full_box, shrinking, circle, sliding, rectangle = boxes
    assert full_box[2] - full_box[0] > shrinking[2] - shrinking[0] > circle[2] - circle[0]
    assert circle[0] < sliding[0] < rectangle[0]
