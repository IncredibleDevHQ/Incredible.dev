"""Where a take falls in a camera's own recording of it, found by sound: code, never a model.

A person records a chapter in the studio while their camera rolls. The studio's take has the
marks (where each line starts); the camera's file has the better picture and sound. Both heard
the same words, so the loudness of the two recordings rises and falls together. This finds the
moment in the camera's file where the take begins by sliding one over the other: first in
fifths of a second across the whole file, then in hundredths around the best place. It is
refused, with the reason in words, when the two don't sound alike, when they sound alike in more
than one place, or when the camera wasn't rolling for the whole take.

The loudness curves are made by ffmpeg on the thread's computer (`ENVELOPE`, a hundred values a
second); this module only compares them, so it needs nothing beyond Python itself.
"""

from __future__ import annotations

import array
import math
import operator
from collections.abc import Sequence
from dataclasses import dataclass

#: Values a second in a loudness curve.
RATE = 100
#: The ffmpeg filters that make a recording's loudness curve: its sound as one channel, kept to
#: the voice's band, squared and smoothed to a tenth of a second, a hundred values a second.
ENVELOPE = (
    "aformat=sample_fmts=flt:channel_layouts=mono,aresample=16000,highpass=f=120,"
    "lowpass=f=4000,aeval=val(0)*val(0),lowpass=f=10,aresample=100,aformat=sample_fmts=flt"
)
#: The coarse search's step, in values of the curve: a fifth of a second.
COARSE = 20
#: How far either side of the coarse search's best place the fine search looks, in seconds.
FINE_REACH = 0.4
#: A place this far from the best is another place, for the second-best match (seconds).
ELSEWHERE = 2.0
#: At least this much of the take overlaps the camera's file at any place tried.
OVERLAP = 0.6
#: How alike the two must sound where they match (a correlation, 1 the same).
ALIKE = 0.5
#: By how much the best place must beat the next best one.
MARGIN = 0.12
#: The camera may start this long after the take did and stop this long after its last line
#: began (seconds); any later and part of the take has no camera picture.
LATE_START = 0.25
LAST_LINE = 1.0
#: The shortest take that can be matched (seconds): there must be words in it to hear.
SHORTEST = 8.0


class Unmatched(ValueError):
    """The camera's file can't be put under the take. The message says why, for the person."""


@dataclass(frozen=True)
class Match:
    """Where the take begins in the camera's file (seconds: a little before the file's own start
    when the camera began a moment late), how alike the two sound there, and the stretch of the
    camera's file that runs under the take (`begin` to `end`, seconds into the file)."""

    start: float
    score: float
    begin: float
    end: float

    def into(self, t: float) -> float:
        """A moment of the take (seconds) as a moment of the camera's stretch under it."""
        return max(0.0, t + self.start - self.begin)


def curve(raw: bytes) -> list[float]:
    """A loudness curve as ffmpeg wrote it (little-endian 32-bit floats). A smoothing filter can
    ring just below zero, so nothing is let below it."""
    values = array.array("f")
    values.frombytes(raw[: len(raw) - len(raw) % 4])
    if values.itemsize != 4:  # pragma: no cover - every platform Python runs on
        raise RuntimeError("32-bit floats are needed to read a loudness curve")
    return [v if v > 0.0 else 0.0 for v in values]


def _features(loudness: Sequence[float]) -> list[float]:
    """The curve in decibels, with everything quieter than a thousandth of the speech's level
    held at that floor: a pause is a pause whatever the room's noise or the microphone's."""
    if not loudness:
        return []
    ordered = sorted(loudness)
    loud = ordered[int(len(ordered) * 0.9) :]
    floor = max(sum(loud) / len(loud) * 1e-3, 1e-12)
    return [math.log10(v + floor) for v in loudness]


def _pooled(values: Sequence[float], step: int) -> list[float]:
    return [sum(values[i : i + step]) / step for i in range(0, len(values) - step + 1, step)]


def _prefix(values: Sequence[float]) -> tuple[list[float], list[float]]:
    sums, squares = [0.0], [0.0]
    for v in values:
        sums.append(sums[-1] + v)
        squares.append(squares[-1] + v * v)
    return sums, squares


def _scores(take: Sequence[float], camera: Sequence[float], lags: range) -> list[float]:
    """How alike the take and the camera's file sound with the take begun at each lag (in
    values of the curve, into the camera's file), over the part of the take the camera has."""
    t_sums, t_squares = _prefix(take)
    c_sums, c_squares = _prefix(camera)
    out: list[float] = []
    for lag in lags:
        first, last = max(0, -lag), min(len(take), len(camera) - lag)
        n = last - first
        if n < 2:
            out.append(-1.0)
            continue
        cross = sum(map(operator.mul, take[first:last], camera[first + lag : last + lag]))
        t_sum = t_sums[last] - t_sums[first]
        c_sum = c_sums[last + lag] - c_sums[first + lag]
        t_var = (t_squares[last] - t_squares[first]) - t_sum * t_sum / n
        c_var = (c_squares[last + lag] - c_squares[first + lag]) - c_sum * c_sum / n
        if t_var <= 1e-12 or c_var <= 1e-12:
            out.append(-1.0)
            continue
        out.append((cross - t_sum * c_sum / n) / math.sqrt(t_var * c_var))
    return out


def match(take: Sequence[float], camera: Sequence[float], *, last_mark: float = 0.0) -> Match:
    """Where the take (its loudness curve) begins in the camera's file (its curve). `last_mark`
    is where the take's last line begins (seconds): the camera must still be rolling a moment
    after it."""
    take_seconds, camera_seconds = len(take) / RATE, len(camera) / RATE
    if take_seconds < SHORTEST:
        raise Unmatched(f"The take is too short to match by sound ({take_seconds:.0f} s).")
    heard_take, heard_camera = _features(take), _features(camera)
    if max(take, default=0.0) <= 0.0 or max(camera, default=0.0) <= 0.0:
        raise Unmatched("One of the two recordings is silent, so there's nothing to match.")
    coarse_take = _pooled(heard_take, COARSE)
    coarse_camera = _pooled(heard_camera, COARSE)
    least = math.ceil(len(coarse_take) * OVERLAP)
    if len(coarse_camera) < least:
        raise Unmatched(
            f"The camera's file ({camera_seconds:.0f} s) is much shorter than the take "
            f"({take_seconds:.0f} s)."
        )
    lags = range(least - len(coarse_take), len(coarse_camera) - least + 1)
    scores = _scores(coarse_take, coarse_camera, lags)
    best = max(range(len(scores)), key=scores.__getitem__)
    apart = round(ELSEWHERE * RATE / COARSE)
    others = [s for i, s in enumerate(scores) if abs(i - best) > apart]
    runner_up = max(others, default=-1.0)
    around = lags[best] * COARSE
    reach = round(FINE_REACH * RATE)
    fine_lags = range(around - reach, around + reach + 1)
    fine = _scores(heard_take, heard_camera, fine_lags)
    at = max(range(len(fine)), key=fine.__getitem__)
    score = fine[at]
    start = fine_lags[at] / RATE
    if score < ALIKE:
        raise Unmatched(
            f"The camera's file doesn't sound like this take (they match {score:.0%} at best)."
        )
    if scores[best] - runner_up < MARGIN:
        raise Unmatched(
            "The camera's file sounds like this take in more than one place: it may hold "
            "another take of the same lines. Bring the clip with this take alone."
        )
    if start < -LATE_START:
        raise Unmatched(
            f"The camera started {-start:.1f} s after this take began, so its first words "
            "aren't on camera."
        )
    end = min(start + take_seconds, camera_seconds)
    if end - start < last_mark + LAST_LINE:
        raise Unmatched(
            f"The camera stopped {start + take_seconds - end:.0f} s before this take ended, "
            "during its last line."
        )
    return Match(
        start=round(start, 3),
        score=round(score, 3),
        begin=round(max(start, 0.0), 3),
        end=round(end, 3),
    )
