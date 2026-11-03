"""Turns voice notes into text through Sarvam's Saaras model. Hinglish stays as spoken."""

import os
from dataclasses import dataclass

import httpx

SARVAM_URL = "https://api.sarvam.ai/speech-to-text"
MODEL = "saaras:v4"
FILE_NAMES = {
    "audio/ogg": "voice.ogg",
    "audio/opus": "voice.opus",
    "audio/mpeg": "voice.mp3",
    "audio/mp4": "voice.m4a",
    "audio/x-m4a": "voice.m4a",
    "audio/wav": "voice.wav",
    "audio/webm": "voice.webm",
    "audio/aac": "voice.aac",
}


class VoiceError(Exception):
    pass


@dataclass
class Transcript:
    text: str
    language: str | None


def transcribe(audio: bytes, mime: str, mode: str = "codemix", transport: httpx.BaseTransport | None = None) -> Transcript:
    key = os.environ.get("SARVAM_API_KEY")
    if not key:
        raise VoiceError("SARVAM_API_KEY is not set")
    name = FILE_NAMES.get(mime.split(";")[0].strip(), "voice.ogg")
    with httpx.Client(timeout=60, transport=transport) as http:
        try:
            response = http.post(
                SARVAM_URL,
                headers={"api-subscription-key": key},
                files={"file": (name, audio, mime)},
                data={"model": MODEL, "mode": mode},
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise VoiceError(f"Sarvam call failed: {error}") from error
    body = response.json()
    text = (body.get("transcript") or "").strip()
    if not text:
        raise VoiceError("Sarvam returned no text")
    return Transcript(text, body.get("language_code"))
