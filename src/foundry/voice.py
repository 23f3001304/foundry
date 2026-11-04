"""Turns voice notes into text through Sarvam's Saaras model, and replies back through Bulbul. Hinglish stays as spoken."""

import base64
import os
from dataclasses import dataclass

import httpx

SARVAM_URL = "https://api.sarvam.ai/speech-to-text"
MODEL = "saaras:v4"
SPEECH_URL = "https://api.sarvam.ai/text-to-speech"
SPEECH_MODEL = "bulbul:v3"
TRANSLATE_URL = "https://api.sarvam.ai/translate"
# Only this model covers every language Saaras can hear.
TRANSLATE_MODEL = "sarvam-translate:v1"
SPOKEN_LANGUAGES = {"bn-IN", "en-IN", "gu-IN", "hi-IN", "kn-IN", "ml-IN", "mr-IN", "od-IN", "pa-IN", "ta-IN", "te-IN"}
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


def speak(text: str, language: str | None, transport: httpx.BaseTransport | None = None) -> bytes | None:
    """The reply as audio. None means Bulbul has no voice for this language, so reply in translated text."""
    if language not in SPOKEN_LANGUAGES:
        return None
    body = _post(SPEECH_URL, {"text": text, "target_language_code": language, "model": SPEECH_MODEL}, transport)
    if not body.get("audios"):
        raise VoiceError("Sarvam returned no audio")
    return base64.b64decode(body["audios"][0])


def translate(text: str, language: str, transport: httpx.BaseTransport | None = None) -> str:
    if language.startswith("en"):
        return text
    body = _post(TRANSLATE_URL, {"input": text, "source_language_code": "en-IN", "target_language_code": language, "model": TRANSLATE_MODEL}, transport)
    if not body.get("translated_text"):
        raise VoiceError("Sarvam returned no translation")
    return body["translated_text"]


def _post(url: str, payload: dict, transport: httpx.BaseTransport | None) -> dict:
    key = os.environ.get("SARVAM_API_KEY")
    if not key:
        raise VoiceError("SARVAM_API_KEY is not set")
    with httpx.Client(timeout=60, transport=transport) as http:
        try:
            response = http.post(url, headers={"api-subscription-key": key}, json=payload)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise VoiceError(f"Sarvam call failed: {error}") from error
    return response.json()
