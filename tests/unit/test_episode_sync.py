"""A camera's own recording matched to the studio take recorded with it, by sound alone."""

from __future__ import annotations

import math
import random
import struct

import pytest

from design_agent.episode import sync


def speech(seconds: float, seed: int) -> list[float]:
    """A loudness curve like a voice's: syllables in phrases of a few seconds, with pauses."""
    rng = random.Random(seed)  # noqa: S311 - a repeatable test signal, not a secret
    out: list[float] = []
    while len(out) < seconds * sync.RATE:
        for _ in range(int(rng.uniform(1, 4) * 4.5)):
            peak, n = rng.uniform(0.2, 1.0), rng.randint(12, 30)
            out += [peak * math.sin(math.pi * i / n) ** 2 + rng.uniform(0, 0.01) for i in range(n)]
        out += [rng.uniform(0, 0.002) for _ in range(rng.randint(20, 120))]
    return out[: int(seconds * sync.RATE)]


def heard(curve: list[float], gain: float, seed: int) -> list[float]:
    """The same sound through another microphone: louder or quieter, over its own room."""
    rng = random.Random(seed)  # noqa: S311 - a repeatable test signal, not a secret
    return [v * gain + rng.uniform(0, 0.004) for v in curve]


def test_a_take_is_found_in_a_camera_recording_that_ran_longer() -> None:
    take = speech(90, seed=1)
    camera = heard(speech(40, seed=2) + take + speech(30, seed=3), gain=1.7, seed=4)
    found = sync.match(take, camera, last_mark=80.0)
    assert found.start == pytest.approx(40.0, abs=0.02) and found.score > 0.8
    assert (found.begin, found.end) == (found.start, pytest.approx(130.0, abs=0.02))
    # a moment of the take is the same moment of the camera's stretch under it
    assert found.into(12.5) == pytest.approx(12.5)


def test_a_camera_that_began_a_moment_after_the_take_still_matches() -> None:
    take = speech(60, seed=5)
    camera = heard(take[10:] + speech(20, seed=6), gain=0.6, seed=7)
    found = sync.match(take, camera, last_mark=50.0)
    assert found.start == pytest.approx(-0.1, abs=0.02) and found.begin == 0.0
    assert found.into(5.0) == pytest.approx(4.9, abs=0.02) and found.into(0.0) == 0.0


def test_sound_unlike_the_take_is_refused_with_how_alike_it_is() -> None:
    with pytest.raises(sync.Unmatched, match="doesn't sound like this take"):
        sync.match(speech(60, seed=8), heard(speech(120, seed=9), 1.0, seed=10))


def test_a_take_heard_twice_in_the_clip_is_refused() -> None:
    take = speech(45, seed=11)
    camera = heard(speech(10, seed=12) + take + speech(20, seed=13) + take, gain=1.0, seed=14)
    with pytest.raises(sync.Unmatched, match="more than one place"):
        sync.match(take, camera)


def test_a_camera_started_late_or_stopped_early_is_refused() -> None:
    take = speech(60, seed=15)
    late = heard(take[300:] + speech(30, seed=16), gain=1.0, seed=17)
    with pytest.raises(sync.Unmatched, match=r"started 3\.0 s after"):
        sync.match(take, late)
    early = heard(speech(20, seed=18) + take[:5000], gain=1.0, seed=19)
    with pytest.raises(sync.Unmatched, match="stopped 10 s before"):
        sync.match(take, early, last_mark=55.0)
    # stopped after the last line had begun and run a while: the take is just shorter
    found = sync.match(take, early, last_mark=40.0)
    assert found.end - found.begin == pytest.approx(50.0, abs=0.02)


def test_a_take_too_short_or_a_silent_clip_has_nothing_to_match() -> None:
    with pytest.raises(sync.Unmatched, match="too short"):
        sync.match(speech(5, seed=20), speech(60, seed=21))
    with pytest.raises(sync.Unmatched, match="silent"):
        sync.match(speech(30, seed=22), [0.0] * 6000)


def test_a_curve_is_read_as_ffmpeg_writes_it() -> None:
    raw = struct.pack("<4f", 0.5, -0.001, 0.25, 0.0) + b"\x00\x01"
    assert sync.curve(raw) == [0.5, 0.0, 0.25, 0.0]
