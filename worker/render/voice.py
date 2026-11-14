"""Voice-over generation with automatic provider fallback.

Order: Gemini 3.8 Flash TTS -> Gemini 3.8 Flash-Lite TTS -> ElevenLabs.
Returns None when every provider fails, so the caller can render a silent
video instead of failing the whole job. API keys are never printed.
"""
import base64
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "ChristianReelsFactory/3.0 (voice-over)"

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_TTS_MODELS = ("gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts")
GEMINI_LANGUAGE = "ar-EG"
GEMINI_DEFAULT_VOICE = "Kore"
GEMINI_STYLE = "calm, warm and reassuring narration"


def gemini_keys():
    raw = (
        os.environ.get("GEMINI_API_KEYS", "")
        + ","
        + os.environ.get("GEMINI_API_KEY", "")
    )
    keys = []
    for part in re.split(r"[,\s]+", raw):
        part = part.strip()
        if part and part not in keys:
            keys.append(part)
    return keys


def _post_json(url, payload, headers, timeout=180):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            **headers,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _error_message(error):
    try:
        data = json.loads(error.read().decode("utf-8", errors="replace"))
        return str(data.get("error", {}).get("message", ""))[:200]
    except Exception:
        return ""


def pick_gemini_voice(key):
    override = os.environ.get("REEL_VOICE", "").strip()
    if override:
        return override

    try:
        query = urllib.parse.urlencode({
            "language_code": GEMINI_LANGUAGE,
            "type": "prebuilt",
            "page_size": 20,
        })
        request = urllib.request.Request(
            f"{GEMINI_BASE}/voices?{query}",
            headers={"x-goog-api-key": key, "User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        for voice in data.get("voices") or []:
            voice_id = voice.get("id") or voice.get("name")
            if voice_id:
                print("Voice library pick:", voice_id,
                      "|", voice.get("display_name", ""))
                return voice_id
    except Exception as error:
        print("Voice library lookup failed:", type(error).__name__)

    return GEMINI_DEFAULT_VOICE


def try_gemini(text, out_path):
    keys = gemini_keys()
    if not keys:
        print("Gemini TTS skipped: no GEMINI_API_KEY(S) configured.")
        return False

    voice = pick_gemini_voice(keys[0])
    print("Gemini TTS voice:", voice)

    payload = {
        "contents": [{
            "role": "user",
            "parts": [{
                "text": text,
                "speech_metadata": {"style": GEMINI_STYLE},
            }],
        }],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"voice": voice}},
        },
    }

    for model in GEMINI_TTS_MODELS:
        url = f"{GEMINI_BASE}/models/{model}:generateContent"
        for number, key in enumerate(keys, start=1):
            try:
                raw = _post_json(url, payload, {"x-goog-api-key": key})
                data = json.loads(raw.decode("utf-8"))
                encoded = (
                    data["candidates"][0]["content"]["parts"][0]
                    ["inlineData"]["data"]
                )
                audio = base64.b64decode(encoded)
                if not audio.startswith(b"RIFF"):
                    raise RuntimeError("unexpected audio format")
                out_path.write_bytes(audio)
                print(f"Gemini TTS OK: {model} (key #{number})")
                return True

            except urllib.error.HTTPError as error:
                print(
                    f"Gemini TTS {model} key #{number}: HTTP {error.code}",
                    _error_message(error),
                )
                if error.code != 429:
                    break

            except Exception as error:
                print(f"Gemini TTS {model} key #{number} failed:",
                      type(error).__name__, str(error)[:200])

    return False


def try_elevenlabs(text, out_path):
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    voice = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
    if not key or not voice:
        print("ElevenLabs skipped: not configured.")
        return False

    try:
        raw = _post_json(
            "https://api.elevenlabs.io/v1/text-to-speech/"
            + urllib.parse.quote(voice),
            {"text": text, "model_id": "eleven_multilingual_v2"},
            {"xi-api-key": key, "Accept": "audio/mpeg"},
        )
        if len(raw) < 1000:
            raise RuntimeError("audio response too small")
        out_path.write_bytes(raw)
        print("ElevenLabs TTS OK")
        return True

    except urllib.error.HTTPError as error:
        print("ElevenLabs HTTP error:", error.code, _error_message(error))
    except Exception as error:
        print("ElevenLabs failed:", type(error).__name__, str(error)[:200])
    return False


def generate_voice(text, work_dir):
    work_dir = Path(work_dir)

    wav_path = work_dir / "voice.wav"
    if try_gemini(text, wav_path):
        return wav_path

    mp3_path = work_dir / "voice.mp3"
    if try_elevenlabs(text, mp3_path):
        return mp3_path

    print("All voice providers failed. The video will have no audio.")
    return None


def audio_duration(path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())
