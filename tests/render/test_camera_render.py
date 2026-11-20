"""A camera's 4K clip on the designer's computer: brought in beside the studio's take of the same
words, found in it by sound, cut once into the film's copy and a copy for 4K, and a chapter's
film rendered in 4K from that copy. The sound and picture are made here: a tone gated in an
irregular rhythm stands in for a voice, a flat 10-bit 4:2:2 picture for the camera's.

    uv run design-agent sandbox build
    uv run pytest -q -m render tests/render/test_camera_render.py
"""

from __future__ import annotations

import copy
import json
import secrets
import subprocess
import time
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from design_agent.episode import film, picture, sketch, timeline, units
from design_agent.runtime.sandbox.docker import DockerLimits, DockerSandboxRunner
from design_agent.surfaces.web import episode_render
from design_agent.surfaces.web.agent import AgentHost
from design_agent.surfaces.web.computer import PROJECTS, Computer
from tests.render.test_gates_render import DOCKER, IMAGE, _image_available
from tests.unit.test_web_episode import house, planned, settle  # noqa: F401 - the fixture

pytestmark = [
    pytest.mark.render,
    pytest.mark.skipif(
        not _image_available(), reason=f"docker or the {IMAGE} image is unavailable"
    ),
]

#: A voice's rise and fall, as a tone that sounds and stops in a rhythm that never repeats, and
#: another rhythm for what the camera heard before and after the take.
SAID = "0.6*sin(2*PI*240*t)*gt(sin(2*PI*0.83*t)+sin(2*PI*1.71*t+1)+sin(2*PI*0.37*t+2),0.4)"
OTHER = "0.6*sin(2*PI*240*t)*gt(sin(2*PI*0.61*t+3)+sin(2*PI*1.37*t)+sin(2*PI*0.53*t+1),0.4)"


@pytest.fixture
async def computer(tmp_path: Path) -> AsyncIterator[Computer]:
    """A thread's own computer, as the product makes one, gone with its files afterwards."""
    runner = DockerSandboxRunner(
        image=IMAGE, prefix="design-agent-test", limits=DockerLimits(vcpus=4, mem_gib=6)
    )
    thread = f"camera-{secrets.token_hex(4)}"
    yield Computer(SimpleNamespace(runner=runner), thread, tmp_path)  # type: ignore[arg-type]
    assert DOCKER is not None
    name, volume = runner.names_for(thread)
    subprocess.run([DOCKER, "rm", "-f", name], capture_output=True, check=False)
    subprocess.run([DOCKER, "volume", "rm", volume], capture_output=True, check=False)


def probe(computer: Computer, path: str) -> dict[str, Any]:
    ran = computer.run(
        "ffprobe -v error -show_entries stream=codec_type,width,height,r_frame_rate,pix_fmt"
        f":format=duration -of json {path}"
    )
    assert ran.ok, ran.output
    return dict(json.loads(ran.output))


async def test_a_cameras_4k_clip_is_matched_cut_and_rendered_in_4k(
    house: AgentHost,  # noqa: F811 - the fixture
    computer: Computer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    episode_id = await planned(house)
    view = house.episodes.view(episode_id)
    chapter = view["plan"]["chapters"][0]
    lines = [f["id"] for b in chapter["beats"] for f in b["frames"]]
    made = f"{PROJECTS}/fixtures"
    ran = computer.run(
        f"mkdir -p {made} && cd {made} && "
        f"ffmpeg -v error -y -f lavfi -i \"aevalsrc='{SAID}':s=48000:d=12\" "
        '-af "lowpass=f=5000,volume=0.5" -c:a aac take.m4a && '
        f"ffmpeg -v error -y -f lavfi -i \"aevalsrc='{OTHER}':s=48000:d=4\" "
        f"-f lavfi -i \"aevalsrc='{SAID}':s=48000:d=12\" -f lavfi -i \"aevalsrc='{OTHER}':s=48000:d=4\" "
        '-f lavfi -i "color=c=0x2f6f4f:s=3840x2160:r=30000/1001:d=20" '
        '-filter_complex "[0:a][1:a][2:a]concat=n=3:v=0:a=1,volume=1.6[a]" -map 3:v -map "[a]" '
        "-c:v libx265 -preset ultrafast -pix_fmt yuv422p10le -tag:v hvc1 "
        "-x265-params log-level=error -c:a pcm_s16le -ac 2 C0001.MOV 2>&1 | grep -v mempolicy",
        timeout=600,
    )
    camera_file = tmp_path / "C0001.MOV"
    with camera_file.open("wb") as out:
        computer.get_into(f"{made}/C0001.MOV", out)
    assert probe(computer, f"{made}/C0001.MOV")["streams"][0]["pix_fmt"] == "yuv422p10le", ran
    # the studio's take of the same words: its sound, and a mark where each line began
    sound = house.save_file_from(
        view["thread_id"],
        "take.m4a",
        lambda out: computer.get_into(f"{made}/take.m4a", out),
        origin="episode",
    )
    step = 10.0 / len(lines)
    studio = house.store.add_take(
        {
            "episode_id": episode_id,
            "chapter": chapter["id"],
            "frame": "",
            "seconds": 12.0,
            "marks": [{"frame": f, "t": round(step * i, 3)} for i, f in enumerate(lines)],
            "video": "",
            "audio": sound["id"],
            "kept": True,
            "added_by": "you",
        }
    )
    monkeypatch.setattr(house.episodes, "_computer", lambda episode: computer)

    house.episodes.bring_take(
        episode_id,
        by="you",
        chapter=chapter["id"],
        name="C0001.MOV",
        source=camera_file,
        staged=False,
        guide=studio["id"],
    )
    await settle(lambda: not house.episodes._busy(episode_id), seconds=600)
    view = house.episodes.view(episode_id)
    assert view["imports"] == [], view["imports"]
    take = view["takes"][-1]
    found = take["recording"]["matched"]
    assert take["kept"] and found["start"] == pytest.approx(4.0, abs=0.05) and found["score"] > 0.7
    assert take["marks"] == studio["marks"] and take["seconds"] == pytest.approx(12.0, abs=0.1)
    takes = f"{PROJECTS}/{episode_id}/takes"
    for ending, (width, height) in (("mp4", (1920, 1080)), ("uhd.mp4", (3840, 2160))):
        seen = probe(computer, f"{takes}/{take['id']}.{ending}")
        picture_of = next(s for s in seen["streams"] if s["codec_type"] == "video")
        assert (picture_of["width"], picture_of["height"]) == (width, height)
        assert picture_of["r_frame_rate"] == "30/1" and picture_of["pix_fmt"] == "yuv420p"
        assert float(seen["format"]["duration"]) == pytest.approx(12.0, abs=0.1)
    assert take["uhd"]["size"] > 0 and take["video"]["size"] > 0 and take["audio"]["size"] > 0

    # the chapter's film, in 4K, its window showing the copy for 4K
    episode = house.store.episode(episode_id)
    assert episode is not None
    full = copy.deepcopy(house.episodes._full(episode) or {})
    full["chapters"] = full["chapters"][:1]
    full["marks"] = [m for m in full["marks"] if m["mark"] != "chapter-card"]
    kept = [t for t in house.store.takes(episode_id) if t["id"] == take["id"]]
    clock = timeline.schedule(full, kept)
    found_units = units.units(full)
    pictures = {u["id"]: sketch.built(picture.brief(u, full)) for u in found_units}
    project = film.project(
        full,
        clock,
        found_units,
        pictures,
        takes={
            take["id"]: {"video": f"takes/{take['id']}.mp4", "audio": f"takes/{take['id']}.m4a"}
        },
    )
    folder = f"{PROJECTS}/{episode_id}/render_test/film"
    computer.put([(f"{folder}/{path}", text.encode()) for path, text in project.items()])
    linked = computer.run(
        f"mkdir -p {folder}/takes {folder}/out && ln -f {takes}/{take['id']}.uhd.mp4 "
        f"{folder}/takes/{take['id']}.mp4 && ln -f {takes}/{take['id']}.m4a "
        f"{folder}/takes/{take['id']}.m4a && {episode_render.launch(folder, 'render_test', '4k')}"
    )
    assert linked.ok, linked.output
    until = time.monotonic() + 900
    while time.monotonic() < until:
        state = computer.run(episode_render.probe(folder, "render_test")).output.partition("\n")[0]
        if state.strip() != "running":
            break
        time.sleep(3)
    assert state.strip() == "0", computer.run(f"tail -20 {folder}/render.log").output
    rendered = probe(computer, f"{folder}/out/episode.mp4")
    shown = next(s for s in rendered["streams"] if s["codec_type"] == "video")
    assert (shown["width"], shown["height"]) == (3840, 2160)
    assert float(rendered["format"]["duration"]) == pytest.approx(clock["total"], abs=0.2)
