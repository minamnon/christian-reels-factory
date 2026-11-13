import json
import math
import os
import re
import html
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, features


WIDTH = 1080
HEIGHT = 1920
FPS = 30

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
COMMONS_USER_AGENT = (
    "ChristianReelsFactory/1.0 "
    "(automated educational video production)"
)

ROOT = Path.cwd()
OUTPUT = ROOT / "output"
WORK = ROOT / "render_work"

OUTPUT.mkdir(exist_ok=True)
WORK.mkdir(exist_ok=True)


IMAGE_KEYWORDS = {
    "غفران": "forgiveness Christian prayer",
    "سامح": "forgiveness Christian prayer",
    "المسامحة": "forgiveness Christian prayer",
    "محبة": "Christian love Jesus",
    "الحب": "Christian love Jesus",
    "يسوع": "Jesus Christ",
    "المسيح": "Jesus Christ",
    "صلاة": "Christian prayer praying",
    "الصلاة": "Christian prayer praying",
    "يصلي": "Christian prayer praying",
    "صليب": "Christian cross",
    "الصليب": "Christian cross",
    "رجاء": "Christian hope sunrise",
    "الأمل": "Christian hope sunrise",
    "إيمان": "Christian faith Bible",
    "الايمان": "Christian faith Bible",
    "الخوف": "fear hope Christian",
    "قلق": "anxiety prayer",
    "السلام": "peace Christian nature",
    "سلام": "peace Christian nature",
    "نعمة": "Christian grace",
    "التوبة": "repentance Christian",
    "توبة": "repentance Christian",
    "القيامة": "Resurrection of Jesus",
    "قيامة": "Resurrection of Jesus",
    "ميلاد": "Nativity of Jesus",
    "الميلاد": "Nativity of Jesus",
    "مريم": "Virgin Mary Christian",
    "يوسف": "Saint Joseph Christian",
    "موسى": "Moses biblical",
    "داود": "King David biblical",
    "إبراهيم": "Abraham biblical",
    "بطرس": "Saint Peter apostle",
    "بولس": "Saint Paul apostle",
    "الكتاب المقدس": "Holy Bible",
    "الإنجيل": "Holy Bible",
    "الانجيل": "Holy Bible",
    "الراعي": "Good Shepherd Jesus sheep",
    "خروف": "sheep shepherd",
    "الرحمة": "mercy Christian",
    "رحمة": "mercy Christian",
    "الصبر": "patience Christian prayer",
    "صبر": "patience Christian prayer",
    "الخطية": "repentance Christian",
    "الخطيئة": "repentance Christian",
    "الخلاص": "Christian salvation cross",
    "نور": "light church sunlight",
    "النور": "light church sunlight",
    "ظلمة": "darkness light Christian",
    "الظلام": "darkness light Christian",
    "البحر": "Sea of Galilee biblical",
    "العاصفة": "storm sea boat",
    "السفينة": "biblical boat sea",
    "الجبل": "biblical mountain landscape",
    "الكنيسة": "Christian church interior",
    "كنيسة": "Christian church interior",
    "القداس": "Christian church worship",
    "الملاك": "angel Christian art",
    "ملاك": "angel Christian art",
    "السماء": "heaven clouds sunlight",
    "السما": "heaven clouds sunlight",
    "القيود": "chains freedom Christian",
    "حرية": "freedom sunrise landscape",
    "الوحدة": "loneliness person landscape",
    "الحزن": "sadness hope sunrise",
    "حزين": "sadness hope sunrise",
    "الشفاء": "healing prayer Christian",
    "شفاء": "healing prayer Christian",
}


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
            "Arabic text rendering requires Pillow with libraqm support."
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

    raise RuntimeError("Arabic font not found.")


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
            "The script does not contain enough text."
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
    chunk_size = math.ceil(len(sentences) / count)

    scenes = []

    for i in range(0, len(sentences), chunk_size):
        scenes.append(
            " ".join(sentences[i:i + chunk_size])
        )

    return scenes


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


def clean_metadata(value):
    if not value:
        return ""

    value = html.unescape(str(value))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def commons_request(params):
    query = urllib.parse.urlencode(params)

    request = urllib.request.Request(
        f"{COMMONS_API}?{query}",
        headers={
            "User-Agent": COMMONS_USER_AGENT,
            "Accept": "application/json"
        }
    )

    with urllib.request.urlopen(request, timeout=35) as response:
        return json.loads(response.read().decode("utf-8"))


def image_search_query(scene_text, topic):
    combined = f"{topic} {scene_text}".lower()

    for arabic_word, english_query in IMAGE_KEYWORDS.items():
        if arabic_word.lower() in combined:
            return english_query

    return "Jesus Christ Bible Christian prayer"


def allowed_license(license_name):
    license_name = (license_name or "").lower()

    allowed_terms = (
        "public domain",
        "cc0",
        "cc by ",
        "cc-by ",
        "cc by-sa",
        "cc-by-sa"
    )

    return any(term in license_name for term in allowed_terms)


def search_commons_image(scene_text, topic, used_titles):
    search_term = image_search_query(scene_text, topic)

    print("Searching Wikimedia Commons:", search_term)

    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": search_term,
        "gsrnamespace": 6,
        "gsrlimit": 12,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|size|mime",
        "iiurlwidth": 1400
    }

    try:
        data = commons_request(params)
        pages = data.get("query", {}).get("pages", {})

        for page in pages.values():
            title = page.get("title", "")

            if not title or title in used_titles:
                continue

            image_info_list = page.get("imageinfo", [])

            if not image_info_list:
                continue

            info = image_info_list[0]
            mime = info.get("mime", "")

            if not mime.startswith("image/"):
                continue

            width = info.get("width", 0)
            height = info.get("height", 0)

            if width < 600 or height < 400:
                continue

            ext = info.get("extmetadata", {})

            license_name = clean_metadata(
                ext.get("LicenseShortName", {}).get("value", "")
            )

            if not allowed_license(license_name):
                continue

            image_url = info.get("thumburl") or info.get("url")

            if not image_url:
                continue

            author = clean_metadata(
                ext.get("Attribution", {}).get("value", "")
                or ext.get("Artist", {}).get("value", "")
                or "Unknown author"
            )

            image_title = clean_metadata(
                ext.get("ObjectName", {}).get("value", "")
                or title.replace("File:", "")
            )

            description_url = info.get(
                "descriptionurl",
                "https://commons.wikimedia.org/"
            )

            return {
                "title": image_title,
                "author": author,
                "license": license_name,
                "source": description_url,
                "url": image_url,
                "commons_title": title
            }

    except Exception as error:
        print("Wikimedia search unavailable:", str(error))

    return None


def download_image(image_url, destination):
    request = urllib.request.Request(
        image_url,
        headers={
            "User-Agent": COMMONS_USER_AGENT
        }
    )

    with urllib.request.urlopen(request, timeout=45) as response:
        content = response.read()

    if not content:
        raise RuntimeError("Downloaded image is empty.")

    destination.write_bytes(content)

    with Image.open(destination) as image:
        image.verify()

    return True


def make_fallback_background():
    image = Image.new("RGB", (WIDTH, HEIGHT))
    pixels = image.load()

    top = (9, 19, 38)
    bottom = (35, 47, 66)

    for y in range(HEIGHT):
        ratio = y / HEIGHT

        color = tuple(
            int(top[c] * (1 - ratio) + bottom[c] * ratio)
            for c in range(3)
        )

        for x in range(WIDTH):
            pixels[x, y] = color

    return image


def add_scene_text(image, text):
    image = image.convert("RGBA")

    overlay = Image.new(
        "RGBA",
        (WIDTH, HEIGHT),
        (0, 0, 0, 0)
    )

    overlay_draw = ImageDraw.Draw(overlay)

    overlay_draw.rectangle(
        (0, 0, WIDTH, 340),
        fill=(0, 0, 0, 55)
    )

    overlay_draw.rectangle(
        (0, 950, WIDTH, HEIGHT),
        fill=(0, 0, 0, 145)
    )

    image = Image.alpha_composite(image, overlay)
    draw = ImageDraw.Draw(image)

    font = get_font(58)
    lines = wrap_text(draw, text, font, 900)

    if len(lines) > 6:
        lines = lines[:6]

    line_height = 100
    total_height = len(lines) * line_height
    start_y = 1110 + max(0, (520 - total_height) // 2)

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
            fill=(0, 0, 0, 220),
            direction="rtl",
            language="ar"
        )

        draw.text(
            (x, y),
            line,
            font=font,
            fill=(255, 250, 235, 255),
            direction="rtl",
            language="ar"
        )

    return image.convert("RGB")


def add_image_credit(image, image_info):
    if not image_info:
        return image

    image = image.convert("RGBA")
    draw = ImageDraw.Draw(image, "RGBA")

    draw.rectangle(
        (0, 1835, WIDTH, HEIGHT),
        fill=(0, 0, 0, 175)
    )

    font = get_font(19)

    title = image_info.get("title", "Image")
    author = image_info.get("author", "Unknown author")
    license_name = image_info.get("license", "License not specified")

    line_one = f"Image: {title[:65]} | {author[:65]}"
    line_two = (
        f"Wikimedia Commons | {license_name} | Cropped for video"
    )

    draw.text(
        (WIDTH // 2, 1865),
        line_one,
        font=font,
        fill=(255, 255, 255, 235),
        anchor="mm",
        direction="ltr",
        language="en"
    )

    draw.text(
        (WIDTH // 2, 1905),
        line_two,
        font=font,
        fill=(230, 220, 200, 235),
        anchor="mm",
        direction="ltr",
        language="en"
    )

    return image.convert("RGB")


def make_scene_image(index, scene_text, topic, used_titles):
    image_info = search_commons_image(
        scene_text,
        topic,
        used_titles
    )

    if image_info:
        image_path = WORK / f"source_{index:02d}.img"

        try:
            download_image(
                image_info["url"],
                image_path
            )

            with Image.open(image_path) as source:
                source = source.convert("RGB")

                image = ImageOps.fit(
                    source,
                    (WIDTH, HEIGHT),
                    method=Image.Resampling.LANCZOS,
                    centering=(0.5, 0.42)
                )

            used_titles.add(image_info["commons_title"])

            print(
                "Using image:",
                image_info["title"],
                "|",
                image_info["license"]
            )

        except Exception as error:
            print("Image download failed:", str(error))
            image = make_fallback_background()
            image_info = None

    else:
        print("No suitable licensed image found; using fallback.")
        image = make_fallback_background()

    image = add_scene_text(image, scene_text)
    image = add_image_credit(image, image_info)

    return image


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

    duration_text = os.environ.get(
        "REEL_DURATION", "35"
    ).strip()

    if not script:
        raise ValueError("REEL_SCRIPT is empty.")

    try:
        total_duration = float(duration_text)
    except (TypeError, ValueError):
        raise ValueError(
            "REEL_DURATION must be a number of seconds."
        )

    if total_duration < 5 or total_duration > 180:
        raise ValueError(
            "REEL_DURATION must be between 5 and 180 seconds."
        )

    check_arabic_support()

    narration = clean_script(script)
    scenes = split_scenes(narration)

    if not scenes:
        raise ValueError("No scenes could be created from the script.")

    scene_duration = total_duration / len(scenes)

    print("Silent video mode enabled.")
    print("ElevenLabs will not be called.")
    print(f"Target duration: {total_duration:.1f} seconds")
    print(f"Scenes: {len(scenes)}")

    clip_paths = []
    used_titles = set()

    for index, scene in enumerate(scenes):
        print(
            f"Creating scene {index + 1}/{len(scenes)}..."
        )

        image_path = WORK / f"scene_{index:02d}.png"
        clip_path = WORK / f"clip_{index:02d}.mp4"

        make_scene_image(
            index,
            scene,
            topic,
            used_titles
        ).save(image_path)

        render_scene(
            image_path,
            scene_duration,
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

    safe_topic = re.sub(
        r"[^a-zA-Z0-9_-]+",
        "-",
        topic
    ).strip("-")

    if not safe_topic:
        safe_topic = "christian-reel"

    final_path = OUTPUT / f"{safe_topic[:35]}-silent.mp4"

    print("Joining silent video scenes...")

    run([
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c:v", "libx264",
        "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-an",
        "-movflags", "+faststart",
        str(final_path)
    ])

    print(f"SUCCESS: {final_path}")
    print(
        f"Silent video duration target: {total_duration:.1f} seconds"
    )


if __name__ == "__main__":
    main()
