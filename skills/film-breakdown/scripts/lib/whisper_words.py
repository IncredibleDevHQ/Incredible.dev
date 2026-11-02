"""Word-timed transcript of a voice-over with faster-whisper (optional extra of film-breakdown).

Usage: python3 whisper_words.py <audio.wav> [model]   (default small.en; prints JSON on stdout)
No VAD, beam 5, no conditioning on earlier text, so each phrase is timed on its own.
"""

import json
import sys

from faster_whisper import WhisperModel

wav = sys.argv[1]
name = sys.argv[2] if len(sys.argv) > 2 else "small.en"
model = WhisperModel(name, device="cpu", compute_type="int8")
segments, info = model.transcribe(
    wav,
    word_timestamps=True,
    vad_filter=False,
    beam_size=5,
    condition_on_previous_text=False,
    language="en" if name.endswith(".en") else None,
)
out = {"language": info.language, "segments": [], "words": []}
for s in segments:
    out["segments"].append(
        {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
    )
    for w in s.words or []:
        out["words"].append({"w": w.word, "s": w.start, "e": w.end, "p": w.probability})
json.dump(out, sys.stdout)
