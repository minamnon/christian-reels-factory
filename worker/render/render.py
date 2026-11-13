
import json
import math
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, features


WIDTH = 1080
HEIGHT = 1920
FPS = 30

VOICE_MODEL = "eleven_multilingual_v2"
API_BASE = "https://api.elevenlabs.io/v1"
VOICES_URL = "https://api.elevenlabs.io/v2/voices"

ROOT = Path.cwd()
OUTPUT = ROOT / "output"
WORK = ROOT / "render_work"

OUTPUT.mkdir(exist_ok=True)
WORK.mkdir(exist_ok=True)


def run(command):
    subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )


def check_arabic_support():
    if not features.check_feature("raqm"):
        raise RuntimeError(
            "Arabic text rendering requires Pillow with libraqm support. "
            "Install libraqm and rebuild Pillow in the workflow."
        )


def get_font(size):
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    ]

    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(
                path,
                size,
                layout_engine=ImageFont.Layout.RAQM
            )

    result = subprocess.run(
        ["fc-match", "-f", "%{file}", "Noto Naskh Arabic"],
        capture_output=True,
        text=True
    )

    path = result.stdout.strip()

    if path and Path(path).exists():
        return ImageFont.truetype(
            path,
            size,
            layout_engine=ImageFont.Layout.RAQM
        )

    raise RuntimeError(
        "Arabic font not found. Install fonts-noto-core."
    )


def elevenlabs_request(url, api_key, method="GET", payload=None):
    headers = {
        "xi-api-key": api_key,
        "Accept": "application/json"
    }

    data = None

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method
    )

    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return response.read()

    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")

        if error.code == 401:
            raise RuntimeError(
                "ElevenLabs API key is invalid or unauthorized."
            )

        if error.code == 402:
            raise RuntimeError(
                "ElevenLabs account has insufficient credits. "
                "No paid fallback will be used."
            )

        if error.code == 429:
            raise RuntimeError(
                "ElevenLabs free usage limit or rate limit reached. "
                "Wait for the limit to reset."
            )

        raise RuntimeError(
            f"ElevenLabs API error {error.code}: {details[:1000]}"
        )

    except urllib.error.URLError as error:
        raise RuntimeError(
            f"Cannot connect to ElevenLabs: {error.reason}"
        )


def choose_arabic_voice(api_key):
    configured_voice = os.environ.get(
        "ELEVENLABS_VOICE_ID", ""
    ).strip()

    if configured_voice:
        print("Using configured ElevenLabs voice ID.")
        return configured_voice

    query = urllib.parse.urlencode({
        "language": "ar",
        "page_size": 100
    })

    raw = elevenlabs_request(
        f"{VOICES_URL}?{query}",
        api_key
    )

    data = json.loads(raw.decode("utf-8"))
    voices = data.get("voices", [])

    candidates = []

    for voice in voices:
        voice_id = voice.get("voice_id")

        if not voice_id:
            continue

        verified = voice.get("verified_languages", [])

        for language in verified:
            language_name = str(
                language.get("language", "")
            ).lower()

            language_id = str(
                language.get("language_id", "")
            ).lower()

            model_ids = language.get("model_id", [])

            if isinstance(model_ids, str):
                model_ids = [model_ids]

            supports_model = (
                not model_ids
                or VOICE_MODEL in model_ids
            )

            is_arabic = (
                "arabic" in language_name
                or language_id == "ar"
            )

            if is_arabic and supports_model:
                candidates.append(voice)
                break

    if not candidates:
        raise RuntimeError(
            "No Arabic voice verified for this account was found. "
            "Choose an Arabic voice available in your account and "
            "add its ID as ELEVENLABS_VOICE_ID in GitHub Secrets."
        )

    selected = candidates[0]

    print(
        "Selected Arabic voice:",
        selected.get("name", "Arabic voice")
    )

    return selected["voice_id"]


def create_voice(text, destination):
    api_key = os.environ.get(
        "ELEVENLABS_API_KEY", ""
    ).strip()

    if not api_key:
        raise RuntimeError(
            "Missing ELEVENLABS_API_KEY GitHub Secret."
        )

    voice_id = choose_arabic_voice(api_key)

    payload = {
        "text": text,
        "model_id": VOICE_MODEL,
        "voice_settings": {
            "stability": 0.55,
            "similarity_boost": 0.75,
            "style": 0.15,
            "use_speaker_boost": True
        }
    }

    url = (
        f"{API_BASE}/text-to-speech/"
        f"{urllib.parse.quote(voice_id, safe='')}"
        "?output_format=mp3_44100_128"
    )

    print("Generating narration with ElevenLabs...")

    audio = elevenlabs_request(
        url,
        api_key,
        method="POST",
        payload=payload
    )

    if not audio:
        raise RuntimeError(
            "ElevenLabs returned an empty audio file."
        )

    destination.write_bytes(audio)

    print("ElevenLabs narration saved.")


def clean_script(script):
    ignored = (
        "عنوان الريل",
        "وصف المنشور",
        "الهاشتاجات",
        "المرجع الكتابي",
        "هاشتاج"
    )

    lines = []

    for raw in script.splitlines():
        line = raw.strip()

        if not line:
            continue

        if any(line.startswith(x) for x in ignored):
            continue

        line = re.sub(
            r"^(Hook|المشهد الأول|المشهد الثاني|المشهد الثالث|"
            r"المشهد الرابع|المشهد الخامس|الرسالة الختامية)\s*[:：\-]\s*",
            "",
            line,
            flags=re.IGNORECASE
        )

        line = re.sub(r"^[•\-*]\s*", "", line)
        line = re.sub(r"\([^)]*\)", "", line)
        line = line.strip()

        if line and len(line) > 2:
            lines.append(line)

    text = " ".join(lines)
    text = re.sub(r"\s+", " ", text).strip()

    if len(text) < 30:
        raise ValueError(
            "The script does not contain enough narration text."
        )

    return text


def split_scenes(text):
    sentences = re.split(r"(?<=[.!؟?])\s+", text)
    sentences = [
        sentence.strip()
        for sentence in sentences
        if len(sentence.strip()) > 8
    ]

    if len(sentences) < 2:
        words = text.split()
        size = max(1, math.ceil(len(words) / 4))

        sentences = [
            " ".join(words[i:i + size])
            for i in range(0, len(words), size)
        ]

    count = min(6, max(3, math.ceil(len(sentences) / 2)))
    scenes = [[] for _ in range(count)]

    for index, sentence in enumerate(sentences):
        scenes[index % count].append(sentence)

    return [
        " ".join(part)
        for part in scenes
        if part
    ]


def wrap_text(draw, text, font, max_width):
    words = text.split()
    lines = []
    current = ""

    for word in words:
        test = f"{current} {word}".strip()

        width = draw.textlength(
            test,
            font=font,
            direction="rtl",
            language="ar"
        )

        if width <= max_width:
            current = test
        else:
            if current:
                lines.append(current)

            current = word

    if current:
        lines.append(current)

    return lines


def make_background(index, text):
    image = Image.new("RGB", (WIDTH, HEIGHT))
    pixels = image.load()

    palettes = [
        ((8, 17, 38), (31, 65, 104)),
        ((13, 22, 42), (82, 65, 83)),
        ((12, 28, 43), (38, 91, 96)),
        ((25, 20, 43), (91, 68, 82)),
        ((8, 24, 39), (65, 78, 102)),
        ((17, 20, 38), (77, 58, 90))
    ]

    top, bottom = palettes[index % len(palettes)]

    for y in range(HEIGHT):
        ratio = y / HEIGHT

        color = tuple(
            int(
                top[c] * (1 - ratio)
                + bottom[c] * ratio
            )
            for c in range(3)
        )

        for x in range(WIDTH):
            pixels[x, y] = color

    draw = ImageDraw.Draw(image, "RGBA")

    for radius in range(500, 80, -35):
        alpha = max(2, 18 - radius // 40)

        draw.ellipse(
            (
                WIDTH // 2 - radius,
                390 - radius,
                WIDTH // 2 + radius,
                390 + radius
            ),
            outline=(255, 225, 174, alpha),
            width=3
        )

    draw.polygon(
        [
            (WIDTH // 2 - 30, 0),
            (WIDTH // 2 + 30, 0),
            (WIDTH // 2 + 430, 1150),
            (WIDTH // 2 - 430, 1150)
        ],
        fill=(255, 238, 205, 12)
    )

    draw.polygon(
        [
            (0, 1320),
            (220, 1120),
            (450, 1320),
            (700, 1080),
            (1080, 1350),
            (1080, 1920),
            (0, 1920)
        ],
        fill=(5, 12, 27, 170)
    )

    draw.line(
        (70, 250, WIDTH - 70, 250),
        fill=(235, 210, 160, 110),
        width=2
    )

    draw.line(
        (70, 1650, WIDTH - 70, 1650),
        fill=(235, 210, 160, 110),
        width=2
    )

    font = get_font(58)
    lines = wrap_text(draw, text, font, 850)

    if len(lines) > 6:
        lines = lines[:6]

    line_height = 105
    total_height = len(lines) * line_height
    start_y = (HEIGHT - total_height) // 2

    for line_index, line in enumerate(lines):
        box = draw.textbbox(
            (0, 0),
            line,
            font=font,
            direction="rtl",
            language="ar"
        )

        text_width = box[2] - box[0]
        x = (WIDTH - text_width) // 2
        y = start_y + line_index * line_height

        draw.text(
            (x + 3, y + 5),
            line,
            font=font,
            fill=(0, 0, 0, 180),
            direction="rtl",
            language="ar"
        )

        draw.text(
            (x, y),
            line,
            font=font,
            fill=(255, 248, 230, 255),
            direction="rtl",
            language="ar"
        )

    small_font = get_font(32)

    draw.text(
        (WIDTH // 2, 1770),
        "الكتاب المقدس مسموع",
        font=small_font,
        fill=(232, 215, 179, 220),
        anchor="mm",
        direction="rtl",
        language="ar"
    )

    return image


def audio_duration(path):
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path)
        ],
        capture_output=True,
        text=True,
        check=True
    )

    return float(result.stdout.strip())


def render_scene(image_path, duration, output_path):
    frames = max(
        1,
        int(math.ceil(duration * FPS))
    )

    video_filter = (
        f"zoompan=z='min(zoom+0.00035,1.08)':"
        f"d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS},"
        "format=yuv420p"
    )

    run([
        "ffmpeg", "-y",
        "-loop", "1",
        "-framerate", str(FPS),
        "-i", str(image_path),
        "-t", str(duration),
        "-vf", video_filter,
        "-an",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        str(output_path)
    ])


def main():
    script = os.environ.get(
        "REEL_SCRIPT", ""
    ).strip()

    topic = os.environ.get(
        "REEL_TOPIC", "رسالة روحية"
    ).strip()

    if not script:
        raise ValueError("REEL_SCRIPT is empty.")

    check_arabic_support()

    narration = clean_script(script)
    scenes = split_scenes(narration)

    voice_path = WORK / "narration.mp3"

    print("Preparing Arabic narration...")

    create_voice(
        narration,
        voice_path
    )

    total_duration = audio_duration(voice_path)
    scene_duration = total_duration / len(scenes)

    print(f"Audio duration: {total_duration:.1f} seconds")
    print(f"Scenes: {len(scenes)}")

    clip_paths = []

    for index, scene in enumerate(scenes):
        print(
            f"Creating scene {index + 1}/{len(scenes)}..."
        )

        image_path = WORK / f"scene_{index:02d}.png"
        clip_path = WORK / f"clip_{index:02d}.mp4"

        make_background(
            index,
            scene
        ).save(image_path)

        render_scene(
            image_path,
            scene_duration + 0.15,
            clip_path
        )

        clip_paths.append(clip_path)

    concat_file = WORK / "concat.txt"

    with concat_file.open(
        "w",
        encoding="utf-8"
    ) as file:
        for clip in clip_paths:
            file.write(
                f"file '{clip.resolve()}'\n"
            )

    silent_video = WORK / "silent.mp4"

    run([
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        str(silent_video)
    ])

    safe_topic = re.sub(
        r"[^a-zA-Z0-9_-]+",
        "-",
        topic
    ).strip("-")

    if not safe_topic:
        safe_topic = "christian-reel"

    final_path = OUTPUT / f"{safe_topic[:35]}.mp4"

    print("Combining video and narration...")

    run([
        "ffmpeg", "-y",
        "-i", str(silent_video),
        "-i", str(voice_path),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        str(final_path)
    ])

    print(f"SUCCESS: {final_path}")
    print(f"Duration: {total_duration:.1f} seconds")


if __name__ == "__main__":
    main()
