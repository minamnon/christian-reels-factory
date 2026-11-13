
import asyncio
import math
import os
import re
import shutil
import subprocess
from pathlib import Path

import edge_tts
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display


WIDTH = 1080
HEIGHT = 1920
FPS = 30
VOICE = "ar-EG-SalmaNeural"

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


def shape_arabic(text):
    return get_display(arabic_reshaper.reshape(text))


def get_font(size):
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    ]

    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)

    result = subprocess.run(
        ["fc-match", "-f", "%{file}", "Noto Naskh Arabic"],
        capture_output=True,
        text=True
    )

    path = result.stdout.strip()
    if path and Path(path).exists():
        return ImageFont.truetype(path, size)

    return ImageFont.load_default()


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
        raise ValueError("The script does not contain enough narration text.")

    return text


def split_scenes(text):
    sentences = re.split(r"(?<=[.!؟?])\s+", text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 8]

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

    return [" ".join(part) for part in scenes if part]


def wrap_text(draw, text, font, max_width):
    words = text.split()
    lines = []
    current = ""

    for word in words:
        test = f"{current} {word}".strip()
        visual = shape_arabic(test)

        if draw.textlength(visual, font=font) <= max_width:
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
            int(top[c] * (1 - ratio) + bottom[c] * ratio)
            for c in range(3)
        )

        for x in range(WIDTH):
            pixels[x, y] = color

    draw = ImageDraw.Draw(image, "RGBA")

    # Soft cinematic light circles
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

    # Light beam
    draw.polygon(
        [
            (WIDTH // 2 - 30, 0),
            (WIDTH // 2 + 30, 0),
            (WIDTH // 2 + 430, 1150),
            (WIDTH // 2 - 430, 1150)
        ],
        fill=(255, 238, 205, 12)
    )

    # Distant hills
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

    # Scene text
    font = get_font(58)
    lines = wrap_text(draw, text, font, 850)

    if len(lines) > 6:
        lines = lines[:6]

    line_height = 105
    total_height = len(lines) * line_height
    start_y = (HEIGHT - total_height) // 2

    for line_index, line in enumerate(lines):
        visual = shape_arabic(line)
        box = draw.textbbox((0, 0), visual, font=font)
        text_width = box[2] - box[0]

        x = (WIDTH - text_width) // 2
        y = start_y + line_index * line_height

        draw.text(
            (x + 3, y + 5),
            visual,
            font=font,
            fill=(0, 0, 0, 180)
        )

        draw.text(
            (x, y),
            visual,
            font=font,
            fill=(255, 248, 230, 255)
        )

    small_font = get_font(32)
    brand = shape_arabic("الكتاب المقدس مسموع")
    draw.text(
        (WIDTH // 2, 1770),
        brand,
        font=small_font,
        fill=(232, 215, 179, 220),
        anchor="mm"
    )

    return image


async def create_voice(text, destination):
    communicate = edge_tts.Communicate(
        text,
        VOICE,
        rate="+0%",
        volume="+0%"
    )
    await communicate.save(str(destination))


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
    frames = max(1, int(math.ceil(duration * FPS)))

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
    script = os.environ.get("REEL_SCRIPT", "").strip()
    topic = os.environ.get("REEL_TOPIC", "رسالة روحية").strip()

    if not script:
        raise ValueError("REEL_SCRIPT is empty.")

    narration = clean_script(script)
    scenes = split_scenes(narration)

    voice_path = WORK / "narration.mp3"

    print("Generating Arabic narration...")
    asyncio.run(create_voice(narration, voice_path))

    total_duration = audio_duration(voice_path)
    scene_duration = total_duration / len(scenes)

    print(f"Audio duration: {total_duration:.1f} seconds")
    print(f"Scenes: {len(scenes)}")

    clip_paths = []

    for index, scene in enumerate(scenes):
        print(f"Creating scene {index + 1}/{len(scenes)}...")

        image_path = WORK / f"scene_{index:02d}.png"
        clip_path = WORK / f"clip_{index:02d}.mp4"

        make_background(index, scene).save(image_path)

        render_scene(
            image_path,
            scene_duration + 0.15,
            clip_path
        )

        clip_paths.append(clip_path)

    concat_file = WORK / "concat.txt"

    with concat_file.open("w", encoding="utf-8") as file:
        for clip in clip_paths:
            file.write(f"file '{clip.resolve()}'\n")

    silent_video = WORK / "silent.mp4"

    run([
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        str(silent_video)
    ])

    safe_topic = re.sub(r"[^a-zA-Z0-9_-]+", "-", topic).strip("-")
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
