"""Voice-over generation with automatic provider fallback.

Order: Gemini 3.8 Flash TTS -> Gemini 3.8 Flash-Lite TTS -> ElevenLabs.
Returns None when every provider fails, so the caller can render a silent
video instead of failing the whole job. API keys are never printed.

Dialogue mode: lines written as "Name: text" are voiced one by one, each
speaker with their own voice (see voices.json). Speaker names are never
spoken. Scripts without speaker labels keep the original single-voice path.
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
import math

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


def try_gemini(text, out_path, voice=None, style=None):
    keys = gemini_keys()
    if not keys:
        print("Gemini TTS skipped: no GEMINI_API_KEY(S) configured.")
        return False

    if not voice:
        voice = pick_gemini_voice(keys[0])
    style = style or GEMINI_STYLE
    print("Gemini TTS voice:", voice)

    payload = {
        "contents": [{
            "role": "user",
            "parts": [{
                "text": text,
                "speech_metadata": {"style": style},
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


# =========================================================
# DIALOGUE MODE: characters and voices come from the script
# =========================================================
# No names are configured anywhere. Every "Name: text" line defines a
# character; each character gets a distinct voice, chosen by gender when the
# script (or scene plan) says it, otherwise balanced automatically.

CONFIG_PATH = Path(__file__).with_name("voices.json")
CHARACTER_STYLE = "natural, emotional, conversational Egyptian Arabic dialogue"
NARRATOR = "__narrator__"
NARRATOR_LABELS = {"الرسالة", "الرسالة الختامية", "الراوي", "الختام", "الخاتمة",
                   "narrator", "message"}
SKIP_LABELS = {"الموقع", "الحوار", "المشهد", "hook", "المرجع الكتابي",
               "عنوان الريل", "وصف المنشور", "الهاشتاجات", "الهاشتاج",
               "ملحوظة", "ملاحظة"}
NOT_NAME_START = {"في", "من", "إلى", "الى", "على", "عن", "ده", "دي", "يعني",
                  "قال", "وقال", "لأن", "لكن", "و", "ثم", "بعد", "قبل", "كل",
                  "لما", "إذا", "اذا", "مثل", "زي", "يوم", "الآية", "الاية"}
GAP_SECONDS = 0.25

DEFAULT_MALE = ["Puck", "Charon", "Fenrir", "Orus", "Enceladus", "Iapetus"]
DEFAULT_FEMALE = ["Kore", "Aoede", "Leda", "Zephyr", "Callirrhoe", "Autonoe"]

FEMALE_WORDS = {"أنثى", "انثى", "امرأة", "امراة", "ست", "سيدة", "بنت", "شابة",
                "فتاة", "أم", "ام", "طفلة", "ماما", "تيتة", "جدة", "أخت", "اخت",
                "عروس", "زوجة", "مدرسة"}
MALE_WORDS = {"ذكر", "رجل", "راجل", "شاب", "ولد", "أب", "اب", "ابن", "صبي",
              "عم", "خال", "قس", "كاهن", "أبونا", "ابونا", "جد", "أخ", "اخ",
              "عريس", "زوج", "مدرس", "طفل"}
FEMALE_EN = re.compile(r"\b(woman|women|female|girl|she|her|mother|lady|"
                       r"grandmother|daughter|wife|sister)\b", re.I)
MALE_EN = re.compile(r"\b(man|men|male|boy|he|his|father|priest|grandfather|"
                     r"son|husband|brother)\b", re.I)
# Used only when the script gives no gender hint at all.
FEMALE_NAMES = {"مريم", "مارتا", "ماريا", "ماري", "مارينا", "سارة", "سارا",
                "إيمان", "ايمان", "فيبي", "دميانة", "دميانا", "ميرنا", "مروة",
                "نانسي", "كارولين", "جيهان", "هدى", "منى", "مي", "ميري",
                "إيريني", "ايريني", "أماني", "اماني", "فيرينا", "سوزان",
                "سميرة", "نيفين", "هناء", "رانيا", "نورا", "ليديا", "يوستينا",
                "مارجريت", "بسمة", "هبة", "دينا", "ريم", "مونيكا", "كريستين"}

_LINE = re.compile(
    r"^[\s*•\-]*"
    r"(?P<name>[^\s:：()（）*\"“”«»\d]{2,20}(?:\s[^\s:：()（）*\"“”«»\d]{2,20})?)"
    r"\s*(?:[(（](?P<tag>[^)）]*)[)）])?\s*[*]*\s*[:：]\s*[*]*\s*(?P<text>.+)$"
)


def _clean_spoken(text):
    text = re.sub(r"\([^)]*\)|（[^）]*）", "", text)
    text = re.sub(r"[*“”\"«»]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text):
    out = set()
    for tok in re.split(r"[\s,،/\-]+", str(text)):
        tok = tok.strip()
        if tok:
            out.add(tok)
            if tok.startswith("ال") and len(tok) > 3:
                out.add(tok[2:])
    return out


def _gender_from_text(text):
    """'male' / 'female' / None from a short description or tag."""
    text = str(text or "")
    tokens = _tokens(text)
    if tokens & FEMALE_WORDS or FEMALE_EN.search(text):
        return "female"
    if tokens & MALE_WORDS or MALE_EN.search(text):
        return "male"
    return None


def _scan(script):
    """Parse a script into utterances and per-speaker gender hints."""
    utterances, hints = [], {}
    for raw in str(script).splitlines():
        line = raw.strip()
        if not line:
            continue
        match = _LINE.match(line)
        if match:
            name = match.group("name").strip()
            key = name.lower()
            first = name.split()[0]
            if (key in SKIP_LABELS or name.startswith("المشهد")
                    or first in NOT_NAME_START):
                continue
            text = _clean_spoken(match.group("text"))
            speaker = NARRATOR if key in NARRATOR_LABELS else name
            if speaker != NARRATOR:
                gender = _gender_from_text(match.group("tag"))
                if gender and speaker not in hints:
                    hints[speaker] = gender
            if len(text) > 1:
                utterances.append((speaker, text))
            continue
        text = _clean_spoken(line)
        if len(text) > 2 and not line.startswith(("*", "#")):
            utterances.append((NARRATOR, text))
    if not any(speaker != NARRATOR for speaker, _ in utterances):
        return None, {}
    return utterances, hints


def parse_dialogue(script):
    """[(speaker, text), ...] or None when the script has no speaker labels."""
    return _scan(script)[0]


def load_voice_config():
    config = {"narrator": None, "male": list(DEFAULT_MALE),
              "female": list(DEFAULT_FEMALE), "style": CHARACTER_STYLE}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        config.update({k: v for k, v in data.items() if v not in (None, "", [])})
    except Exception as error:
        print("voices.json not loaded:", type(error).__name__)
    override = os.environ.get("REEL_VOICES", "").strip()
    if override:
        try:
            config.update(json.loads(override))
        except Exception as error:
            print("REEL_VOICES ignored:", type(error).__name__)
    return config


def _plan_genders(plan, speakers):
    """Gender from scene_plan.characters when its keys match speaker names."""
    found = {}
    characters = (plan or {}).get("characters") or {}
    if not isinstance(characters, dict):
        return found
    for speaker in speakers:
        for key, description in characters.items():
            if str(key).strip() == speaker:
                gender = _gender_from_text(
                    description if isinstance(description, str)
                    else json.dumps(description, ensure_ascii=False))
                if gender:
                    found[speaker] = gender
    return found


def assign_voices(utterances, narrator_voice, hints=None, plan=None):
    config = load_voice_config()
    narrator = config.get("narrator") or narrator_voice
    pools = {"male": [v for v in config["male"] if v != narrator],
             "female": [v for v in config["female"] if v != narrator]}
    speakers = []
    for speaker, _ in utterances:
        if speaker != NARRATOR and speaker not in speakers:
            speakers.append(speaker)

    genders = dict(hints or {})
    for speaker, gender in _plan_genders(plan, speakers).items():
        genders.setdefault(speaker, gender)
    for speaker in speakers:
        if speaker not in genders:
            first = speaker.split()[0]
            if first in FEMALE_NAMES or speaker.endswith("ة"):
                genders[speaker] = "female"
    # Still unknown: balance so neighbouring characters sound different.
    for speaker in speakers:
        if speaker not in genders:
            males = sum(1 for g in genders.values() if g == "male")
            females = sum(1 for g in genders.values() if g == "female")
            genders[speaker] = "female" if females < males else "male"

    mapping, used = {NARRATOR: narrator}, {"male": 0, "female": 0}
    for speaker in speakers:
        gender = genders[speaker]
        pool = pools[gender] or pools["male" if gender == "female" else "female"]
        mapping[speaker] = pool[used[gender] % len(pool)]
        used[gender] += 1
    return mapping, genders, config.get("style") or CHARACTER_STYLE


def _ffmpeg(args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def _normalize(src, dst):
    _ffmpeg(["-i", str(src), "-ar", "24000", "-ac", "1",
             "-c:a", "pcm_s16le", str(dst)])


def generate_dialogue(utterances, work_dir, script=None, plan=None):
    """One clip per line, each in its character's voice, joined in order.

    Returns (audio_path, [seconds per utterance]) or None if any line fails,
    so the caller can fall back to the single-voice path.
    """
    work_dir = Path(work_dir)
    hints = _scan(script)[1] if script else {}
    keys = gemini_keys()
    narrator_voice = pick_gemini_voice(keys[0]) if keys else GEMINI_DEFAULT_VOICE
    voices, genders, char_style = assign_voices(
        utterances, narrator_voice, hints, plan)
    print("Characters:", {k: f"{genders[k]}/{voices[k]}"
                          for k in voices if k != NARRATOR},
          "| narrator:", voices[NARRATOR])

    gap = work_dir / "gap.wav"
    _ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
             "-t", str(GAP_SECONDS), "-c:a", "pcm_s16le", str(gap)])

    parts, durations = [], []
    for number, (speaker, text) in enumerate(utterances, start=1):
        raw = work_dir / f"line_{number:02d}.wav"
        style = GEMINI_STYLE if speaker == NARRATOR else char_style
        ok = try_gemini(text, raw, voice=voices[speaker], style=style)
        if not ok:
            raw = work_dir / f"line_{number:02d}.mp3"
            ok = try_elevenlabs(text, raw)
        if not ok:
            print(f"Line {number} could not be voiced; using single voice.")
            return None
        clip = work_dir / f"line_{number:02d}_n.wav"
        _normalize(raw, clip)
        seconds = audio_duration(clip)
        parts.append(clip)
        if number != len(utterances):
            parts.append(gap)
            seconds += GAP_SECONDS
        durations.append(seconds)

    listing = work_dir / "dialogue_list.txt"
    listing.write_text(
        "".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8")
    out = work_dir / "voice.wav"
    _ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing),
             "-c:a", "pcm_s16le", str(out)])
    print(f"Dialogue voice-over: {len(utterances)} lines, "
          f"{sum(durations):.1f}s")
    return out, durations


def strip_speaker_labels(text):
    """Remove leading 'Name:' labels so names are never shown or spoken."""
    lines = []
    for line in str(text).splitlines() or [str(text)]:
        match = _LINE.match(line.strip())
        lines.append(_clean_spoken(match.group("text")) if match
                     else _clean_spoken(line))
    return " ".join(l for l in lines if l)
