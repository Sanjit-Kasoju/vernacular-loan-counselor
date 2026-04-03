"""
voice.py  –  Sarvam AI STT + TTS with proper audio format handling
             audio_recorder_streamlit records as WAV but sometimes with
             wrong headers — we re-encode it before sending to Sarvam.
"""

import os
import io
import wave
import base64
import struct
import requests
from dotenv import load_dotenv

load_dotenv()
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")

SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"

LANG_CODE_MAP = {
    "english": "en-IN",
    "hindi":   "hi-IN",
    "marathi": "mr-IN",
    "tamil":   "ta-IN",
}

LANG_VOICE_MAP = {
    "english": "anushka",
    "hindi":   "anushka",
    "marathi": "anushka",
    "tamil":   "anushka",
}


def _ensure_valid_wav(audio_bytes: bytes) -> bytes:
    """
    audio_recorder_streamlit sometimes returns raw PCM or a WAV with
    wrong sample rate headers. This function re-wraps it into a clean
    16kHz mono 16-bit WAV that Sarvam accepts.
    """
    try:
        # Try reading as WAV first
        with wave.open(io.BytesIO(audio_bytes)) as wf:
            n_channels   = wf.getnchannels()
            sampwidth    = wf.getsampwidth()
            framerate    = wf.getframerate()
            raw_frames   = wf.readframes(wf.getnframes())

        # If stereo, convert to mono by averaging channels
        if n_channels == 2 and sampwidth == 2:
            samples = struct.unpack(f"<{len(raw_frames)//2}h", raw_frames)
            mono    = bytes(struct.pack(
                f"<{len(samples)//2}h",
                *[int((samples[i] + samples[i+1]) / 2) for i in range(0, len(samples)-1, 2)]
            ))
            raw_frames  = mono
            n_channels  = 1

        # Re-write as clean WAV
        out = io.BytesIO()
        with wave.open(out, "wb") as wf_out:
            wf_out.setnchannels(1)
            wf_out.setsampwidth(2)          # 16-bit
            wf_out.setframerate(framerate)  # keep original rate
            wf_out.writeframes(raw_frames)

        return out.getvalue()

    except Exception:
        # If it's not a WAV at all, wrap raw bytes as 16kHz mono WAV
        out = io.BytesIO()
        with wave.open(out, "wb") as wf_out:
            wf_out.setnchannels(1)
            wf_out.setsampwidth(2)
            wf_out.setframerate(16000)
            wf_out.writeframes(audio_bytes)
        return out.getvalue()


def transcribe_audio(audio_bytes: bytes, language: str = "hindi") -> str:
    """
    Convert speech audio → text using Sarvam STT (Saarika v2).
    Automatically fixes audio format before sending.
    """
    if not SARVAM_API_KEY:
        raise ValueError("SARVAM_API_KEY is not set in your .env file.")

    lang_code   = LANG_CODE_MAP.get(language.lower(), "hi-IN")
    clean_audio = _ensure_valid_wav(audio_bytes)

    files = {"file": ("audio.wav", clean_audio, "audio/wav")}
    data  = {
        "language_code":   lang_code,
        "model":           "saarika:v2.5",
        "with_timestamps": "false",
    }
    headers = {"api-subscription-key": SARVAM_API_KEY}

    response = requests.post(
        SARVAM_STT_URL, files=files, data=data,
        headers=headers, timeout=30
    )

    # Show a clear error message if it still fails
    if not response.ok:
        raise ValueError(
            f"Sarvam STT error {response.status_code}: {response.text[:300]}"
        )

    return response.json().get("transcript", "")


def synthesize_speech(text: str, language: str = "hindi") -> bytes:
    """
    Convert text → WAV audio using Sarvam TTS (Bulbul v2).
    Splits long text into chunks if needed.
    """
    if not SARVAM_API_KEY:
        raise ValueError("SARVAM_API_KEY is not set in your .env file.")

    lang_code = LANG_CODE_MAP.get(language.lower(), "hi-IN")
    speaker   = LANG_VOICE_MAP.get(language.lower(), "anushka")

    # Sarvam limit is 500 chars per call — chunk if needed
    chunks    = [text[i:i+490] for i in range(0, len(text), 490)]
    all_audio = b""

    headers = {
        "api-subscription-key": SARVAM_API_KEY,
        "Content-Type": "application/json",
    }

    for chunk in chunks[:3]:   # max 3 chunks (~1500 chars) to keep latency low
        payload = {
            "inputs":               [chunk],
            "target_language_code": lang_code,
            "speaker":              speaker,
            "model":                "bulbul:v2",
            "enable_preprocessing": True,
            "audio_format":         "wav",
        }
        resp = requests.post(SARVAM_TTS_URL, json=payload, headers=headers, timeout=30)

        if not resp.ok:
            raise ValueError(
                f"Sarvam TTS error {resp.status_code}: {resp.text[:300]}"
            )

        audio_b64 = resp.json().get("audios", [""])[0]
        if audio_b64:
            all_audio += base64.b64decode(audio_b64)

    if not all_audio:
        raise ValueError("No audio returned from Sarvam TTS.")

    return all_audio
