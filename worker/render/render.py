import json
import math
import os
import re
import html
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import (
    Image,
    ImageDraw,
    ImageFont,
    ImageOps,
    ImageStat,
    features
)


# =========================================================
# SETTINGS
# =========================================================

WIDTH = 1080
HEIGHT = 1920
FPS = 30

COMMONS_API = "https://commons.wikimedia.org/w/api.php"

COMMONS_USER_AGENT = (
    "ChristianReelsFactory/2.0 "
    "(automated educational video production)"
)

ROOT = Path.cwd()
OUTPUT = ROOT / "output"
WORK = ROOT / "render_work"

OUTPUT.mkdir(exist_ok=True)
WORK.mkdir(exist_ok=True)


# =========================================================
# ARABIC KEYWORDS
# =========================================================

IMAGE_KEYWORDS = {
    "غفران": "forgiveness Christian prayer",
    "سامح": "forgiveness Christian prayer",
    "المسامحة": "forgiveness Christian prayer",
    "محبة": "Christian love compassion",
    "الحب": "Christian love compassion",
    "يسوع": "Jesus Christ",
    "المسيح": "Jesus Christ",
    "صلاة": "Christian prayer praying",
    "الصلاة": "Christian prayer praying",
    "يصلي": "Christian prayer praying",
    "صليب": "Christian cross",
    "الصليب": "Christian cross",
    "رجاء": "Christian hope sunrise",
    "الأمل": "hope sunrise landscape",
    "إيمان": "Christian faith Bible",
    "الايمان": "Christian faith Bible",
    "الخوف": "fear hope Christian",
    "قلق": "anxiety prayer Christian",
    "السلام": "peace Christian nature",
    "سلام": "peaceful nature sunrise",
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


# =========================================================
# SCENE-SPECIFIC IMAGE SEARCH
# =========================================================

SPECIAL_IMAGE_QUERIES = [
    ("دموع", [
        "person praying with tears",
        "comfort sadness Christian prayer"
    ]),
    ("تعب", [
        "person praying outdoors sunrise",
        "Christian hope comfort"
    ]),
    ("انتظار", [
        "sunrise waiting hope landscape",
        "sunrise over mountains"
    ]),
    ("رجاء", [
        "Christian hope sunrise landscape",
        "sunrise golden light"
    ]),
    ("الأمل", [
        "hope sunrise landscape",
        "sunrise golden light"
    ]),
    ("إيمان", [
        "hands holding Bible sunlight",
        "open Bible warm light"
    ]),
    ("الايمان", [
        "hands holding Bible sunlight",
        "open Bible warm light"
    ]),
    ("تمسك", [
        "hands holding cross Bible",
        "hands praying Bible"
    ]),
    ("الظروف", [
        "sunrise after storm landscape",
        "calm sea sunrise"
    ]),
    ("محبة", [
        "Jesus comforting person painting",
        "Christian love compassion"
    ]),
    ("صلاة", [
        "person praying hands sunlight",
        "Christian prayer outdoors"
    ]),
    ("الصلاة", [
        "person praying hands sunlight",
        "Christian prayer outdoors"
    ]),
]


# =========================================================
# GENERAL HELPERS
# =========================================================

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
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
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


def get_credit_font(size):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]

    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)

    return ImageFont.load_default()


# =========================================================
# SCRIPT CLEANING
# =========================================================

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


# =========================================================
# TEXT DRAWING
# =========================================================

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


# =========================================================
# WIKIMEDIA COMMONS
# =========================================================

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
        return json.loads(
            response.read().decode("utf-8")
        )


def image_search_queries(scene_text, topic):
    text = scene_text.lower()

    for word, queries in SPECIAL_IMAGE_QUERIES:
        if word in text:
            return queries

    for arabic_word, english_query in IMAGE_KEYWORDS.items():
        if arabic_word.lower() in text:
            return [
                english_query,
                "Christian hope sunrise landscape"
            ]

    return [
        "Christian hope sunrise landscape",
        "open Bible warm sunlight"
    ]


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

    return any(
        term in license_name
        for term in allowed_terms
    )


def search_commons_image(scene_text, topic, used_titles):
    queries = image_search_queries(scene_text, topic)

    for search_term in queries:
        print(
            "Searching Wikimedia Commons:",
            search_term
        )

        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": search_term,
            "gsrnamespace": 6,
            "gsrlimit": 20,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|size|mime",
            "iiurlwidth": 1600
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

                if width < 700 or height < 500:
                    continue

                ext = info.get("extmetadata", {})

                license_name = clean_metadata(
                    ext.get(
                        "LicenseShortName", {}
                    ).get("value", "")
                )

                if not allowed_license(license_name):
                    continue

                image_url = (
                    info.get("thumburl")
                    or info.get("url")
                )

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
            print(
                "Wikimedia search failed:",
                str(error)
            )
            continue

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


# =========================================================
# FALLBACK BACKGROUND
# =========================================================

def make_fallback_background():
    image = Image.new("RGB", (WIDTH, HEIGHT))
    pixels = image.load()

    # Bright warm sunrise gradient.
    top = (18, 35, 62)
    bottom = (176, 125, 67)

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

    return image


# =========================================================
# SCENE TEXT
# =========================================================

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

    start_y = 1110 + max(
        0,
        (520 - total_height) // 2
    )

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


# =========================================================
# IMAGE CREDITS
# =========================================================

def add_image_credit(image, image_info):
    if not image_info:
        return image

    image = image.convert("RGBA")
    draw = ImageDraw.Draw(image, "RGBA")

    draw.rectangle(
        (0, 1845, WIDTH, HEIGHT),
        fill=(0, 0, 0, 150)
    )

    font = get_credit_font(18)

    title = clean_metadata(
        image_info.get("title", "Image")
    )[:48]

    author = clean_metadata(
        image_info.get("author", "Unknown author")
    )[:42]

    license_name = clean_metadata(
        image_info.get("license", "License")
    )[:35]

    line_one = f"Image: {title} | {author}"
    line_two = f"Wikimedia Commons | {license_name}"

    draw.text(
        (WIDTH // 2, 1870),
        line_one,
        font=font,
        fill=(255, 255, 255, 245),
        anchor="mm"
    )

    draw.text(
        (WIDTH // 2, 1908),
        line_two,
        font=font,
        fill=(245, 230, 205, 245),
        anchor="mm"
    )

    return image.convert("RGB")


# =========================================================
# BUILD SCENE IMAGE
# =========================================================

def make_scene_image(index, scene_text, topic, used_titles):
    image_info = search_commons_image(
        scene_text,
        topic,
        used_titles
    )

    image = None

    if image_info:
        image_path = WORK / f"source_{index:02d}.img"

        try:
            download_image(
                image_info["url"],
                image_path
            )

            with Image.open(image_path) as source:
                source = source.convert("RGB")

                candidate = ImageOps.fit(
                    source,
                    (WIDTH, HEIGHT),
                    method=Image.Resampling.LANCZOS,
                    centering=(0.5, 0.42)
                )

            # Reject very dark images.
            brightness = (
                sum(ImageStat.Stat(candidate).mean) / 3
            )

            print(
                f"Image brightness: {brightness:.1f}"
            )

            if brightness < 38:
                raise ValueError(
                    "Image is too dark. Trying fallback."
                )

            image = candidate
            used_titles.add(
                image_info["commons_title"]
            )

            print(
                "Using image:",
                image_info["title"],
                "|",
                image_info["license"]
            )

        except Exception as error:
            print(
                "Image rejected:",
                str(error)
            )

            image = make_fallback_background()
            image_info = None

    else:
        print(
            "No suitable licensed image found; "
            "using bright fallback."
        )

        image = make_fallback_background()

    image = add_scene_text(
        image,
        scene_text
    )

    image = add_image_credit(
        image,
        image_info
    )

    return image


# =========================================================
# RENDER VIDEO SCENE
# =========================================================

def render_scene(image_path, duration, output_path):
    frames = max(
        1,
        int(math.ceil(duration * FPS))
    )

    video_filter = (
        f"zoompan=z='min(zoom+0.00035,1.08)':"
        f"d={frames}:"
        f"s={WIDTH}x{HEIGHT}:"
        f"fps={FPS},"
        "format=yuv420p"
    )

    run([
        "ffmpeg",
        "-y",
        "-loop", "1",
        "-framerate", str(FPS),
        "-i", str(image_path),
        "-t", str(duration),
        "-vf", video_filter,
        "-an",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        str
