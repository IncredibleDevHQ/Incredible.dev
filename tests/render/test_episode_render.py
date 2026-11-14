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
