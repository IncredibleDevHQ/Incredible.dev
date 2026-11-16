"""Synthetic English narration using an installed offline speech engine."""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

from design_agent.tools.media import Spoken


def engine() -> str | None:
    if sys.platform == "darwin" and shutil.which("say"):
        return "say"
    return "espeak-ng" if shutil.which("espeak-ng") else None


def synthesize(words: str) -> Spoken:
    name = engine()
    if name is None:
        raise ValueError("Local narration needs macOS speech or espeak-ng.")
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "speech.wav"
        if name == "say":
            args = [
                "say",
                "-v",
                "Samantha",
                "-r",
                "165",
                "-o",
                str(output),
                "--file-format=WAVE",
                "--data-format=LEI16@22050",
                "-f",
                "-",
            ]
        else:
            args = ["espeak-ng", "-v", "en-us", "-s", "165", "-w", str(output), "--stdin"]
        # Pass plain text on stdin, including for a line that starts with a dash.
        text = words.replace("[[", "").replace("]]", "")
        result = subprocess.run(  # noqa: S603 - fixed executable and options, narration via stdin
            args, input=text.encode(), capture_output=True, timeout=120, check=False
        )
        if result.returncode or not output.is_file():
            raise ValueError("The local speech engine could not speak this line.")
        audio = output.read_bytes()
    with wave.open(io.BytesIO(audio)) as wav:
        seconds = wav.getnframes() / wav.getframerate()
        if not seconds or not any(wav.readframes(wav.getnframes())):
            raise ValueError("The local speech engine produced an empty recording.")
    return Spoken(audio, seconds, [])
