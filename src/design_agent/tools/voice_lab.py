"""Make a full-length listening copy with a disposable ElevenLabs voice."""

import io
import wave

import httpx

from design_agent.tools.media import ELEVENLABS, MediaKeys, _elevenlabs_error, clone_voice

RATE = 16000
MAX_FRAMES = RATE * 300


def frame_count(data: bytes) -> int:
    try:
        with wave.open(io.BytesIO(data)) as audio:
            frames = int(audio.getnframes())
            if (
                audio.getnchannels() == 1
                and audio.getsampwidth() == 2
                and audio.getframerate() == RATE
                and 0 < frames <= MAX_FRAMES
                and len(audio.readframes(frames)) == frames * 2
            ):
                return frames
    except (wave.Error, EOFError):
        pass
    raise ValueError("Choose a readable audio recording of up to five minutes.")


async def render(
    client: httpx.AsyncClient, keys: MediaKeys, name: str, original: bytes, text: str | None = None
) -> bytes:
    frames = frame_count(original)
    if text is not None and (not text.strip() or len(text) > 2000):
        raise ValueError("Enter between 1 and 2000 characters for the clone to read.")
    clone = await clone_voice(keys, name, [("recording.wav", original)])
    if isinstance(clone, str):
        raise ValueError(clone)
    headers = {"xi-api-key": keys.elevenlabs or ""}
    try:
        if clone.verify:
            raise ValueError("ElevenLabs requires verification for this voice.")
        if text is not None:
            result = await client.post(
                f"{ELEVENLABS}/text-to-speech/{clone.voice_id}",
                headers=headers,
                params={"output_format": "pcm_16000"},
                json={
                    "text": text.strip(),
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {"similarity_boost": 0.9, "stability": 0.5},
                },
            )
        else:
            result = await client.post(
                f"{ELEVENLABS}/voice-changer/{clone.voice_id}",
                headers=headers,
                params={"output_format": "pcm_16000"},
                data={"model_id": "eleven_multilingual_sts_v2"},
                files={"audio": ("recording.wav", original, "audio/wav")},
            )
        if not result.is_success:
            reason = _elevenlabs_error(result)
            if result.status_code in (401, 403) and "speech_to_speech" in reason:
                raise ValueError(
                    "The ElevenLabs API key needs Speech to Speech (Voice Changer) permission. "
                    "Enable it on the workspace key, then retry with this recording."
                )
            raise ValueError(reason)
        pcm = result.content
        # Only reconcile small codec-boundary differences. Never disguise missing speech.
        if not pcm or len(pcm) % 2:
            raise ValueError("ElevenLabs returned incomplete audio.")
        if text is not None:
            frames = len(pcm) // 2
        elif abs(len(pcm) // 2 - frames) > min(RATE // 2, frames // 10):
            raise ValueError("The generated recording has a different duration. Try again.")
        output = io.BytesIO()
        with wave.open(output, "wb") as audio:
            audio.setparams((1, 2, RATE, frames, "NONE", ""))
            audio.writeframes(pcm[: frames * 2].ljust(frames * 2, b"\x00"))
        return output.getvalue()
    except httpx.TimeoutException as exc:
        raise ValueError(
            "ElevenLabs timed out during conversion. You can retry this recording."
        ) from exc
    except httpx.RequestError as exc:
        raise ValueError("The server lost its connection to ElevenLabs during conversion.") from exc
    finally:
        try:
            removed = await client.delete(f"{ELEVENLABS}/voices/{clone.voice_id}", headers=headers)
            if removed.status_code != 404:
                removed.raise_for_status()
        except httpx.HTTPError as exc:
            raise ValueError(
                f"ElevenLabs could not remove temporary voice {clone.voice_id}. "
                "Remove it from My Voices before retrying."
            ) from exc
