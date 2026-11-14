import json
import math
import os
import re
import urllib.error
import html
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageStat, features


# =========================================================
# SETTINGS
# =========================================================

WIDTH = 1080
HEIGHT = 1920
FPS = 30

ROOT = Path.cwd()
OUTPUT = ROOT / "output"
WORK = ROOT / "render_work"
OUTPUT.mkdir(exist_ok=True)
WORK.mkdir(exist_ok=True)

PIXABAY_API = "https://pixabay.com/api/"
OPENVERSE_API = "https://api.openverse.org/v1/images/"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"

USER_AGENT = (
    "ChristianReelsFactory/3.0 "
    "(automated educational video production)"
)

PIXABAY_KEY = os.environ.get("PIXABAY_API_KEY", "").strip()

# Only licenses suitable for reuse with attribution or public-domain terms.
OPENVERSE_LICENSES = "cc0,by,by-sa,pdm"


# =========================================================
# SEARCH TERMS
# =========================================================

IMAGE_KEYWORDS = {
    "غفران": ["forgiveness Christian prayer", "person praying peaceful light"],
    "سامح": ["forgiveness Christian prayer", "reconciliation compassion"],
    "المسامحة": ["forgiveness Christian prayer", "reconciliation compassion"],
    "محبة": ["Christian love compassion", "helping hands kindness"],
    "الحب": ["Christian love compassion", "helping hands kindness"],
    "يسوع": ["Jesus Christ painting", "Jesus Christ religious art"],
    "المسيح": ["Jesus Christ painting", "Jesus Christ religious art"],
    "صلاة": ["person praying hands", "Christian prayer outdoors"],
    "الصلاة": ["person praying hands", "Christian prayer outdoors"],
    "يصلي": ["person praying hands", "Christian prayer outdoors"],
    "صليب": ["Christian cross sunrise", "wooden cross landscape"],
    "الصليب": ["Christian cross sunrise", "wooden cross landscape"],
    "رجاء": ["Christian hope sunrise", "hopeful sunrise landscape"],
    "الأمل": ["hope sunrise landscape", "sunrise golden light"],
    "إيمان": ["hands holding Bible sunlight", "open Bible warm light"],
    "الايمان": ["hands holding Bible sunlight", "open Bible warm light"],
    "الخوف": ["comfort hope person praying", "peaceful sunrise landscape"],
    "قلق": ["anxiety comfort prayer", "person praying peaceful light"],
    "السلام": ["peaceful nature sunrise", "calm lake morning light"],
    "سلام": ["peaceful nature sunrise", "calm lake morning light"],
    "نعمة": ["Christian grace sunlight", "church window sunlight"],
    "التوبة": ["repentance Christian prayer", "person praying church"],
    "توبة": ["repentance Christian prayer", "person praying church"],
    "القيامة": ["Resurrection of Jesus painting", "empty tomb Jesus resurrection"],
    "قيامة": ["Resurrection of Jesus painting", "empty tomb Jesus resurrection"],
    "ميلاد": ["Nativity of Jesus painting", "birth of Jesus manger"],
    "الميلاد": ["Nativity of Jesus painting", "birth of Jesus manger"],
    "مريم": ["Virgin Mary Christian painting", "Virgin Mary religious art"],
    "يوسف": ["Saint Joseph Christian painting", "Saint Joseph religious art"],
    "موسى": ["Moses biblical painting", "Moses bible illustration"],
    "داود": ["King David biblical painting", "David and Goliath painting"],
    "إبراهيم": ["Abraham biblical painting", "Abraham bible illustration"],
    "بطرس": ["Saint Peter apostle painting", "Saint Peter religious art"],
    "بولس": ["Saint Paul apostle painting", "Saint Paul religious art"],
    "الكتاب المقدس": ["Holy Bible open book", "Bible pages sunlight"],
    "الإنجيل": ["Holy Bible open book", "Bible pages sunlight"],
    "الانجيل": ["Holy Bible open book", "Bible pages sunlight"],
    "الراعي": ["Good Shepherd Jesus sheep painting", "shepherd sheep landscape"],
    "الرحمة": ["mercy compassion helping hands", "Christian mercy prayer"],
    "رحمة": ["mercy compassion helping hands", "Christian mercy prayer"],
    "الصبر": ["patience Christian prayer", "person waiting sunrise"],
    "صبر": ["patience Christian prayer", "person waiting sunrise"],
    "الخلاص": ["Christian salvation cross", "cross sunrise landscape"],
    "نور": ["sunlight through church window", "golden sunlight nature"],
    "النور": ["sunlight through church window", "golden sunlight nature"],
    "ظلمة": ["light breaking through clouds", "sunrise after storm"],
    "الظلام": ["light breaking through clouds", "sunrise after storm"],
    "البحر": ["Sea of Galilee landscape", "calm sea sunrise"],
    "العاصفة": ["storm over sea boat", "storm clouds over ocean"],
    "السفينة": ["wooden fishing boat sea", "biblical boat sea"],
    "الجبل": ["mountain sunrise landscape", "biblical mountain landscape"],
    "الكنيسة": ["Christian church interior sunlight", "church stained glass"],
    "كنيسة": ["Christian church interior sunlight", "church stained glass"],
    "القداس": ["Christian church worship", "church congregation prayer"],
    "الملاك": ["angel Christian religious painting", "guardian angel painting"],
    "ملاك": ["angel Christian religious painting", "guardian angel painting"],
    "السماء": ["sunlight clouds sky", "heavenly clouds golden light"],
    "السما": ["sunlight clouds sky", "heavenly clouds golden light"],
    "القيود": ["broken chains freedom", "hands breaking chains"],
    "حرية": ["freedom sunrise landscape", "open road mountain sunrise"],
    "الوحدة": ["lonely person landscape", "person sitting alone sunset"],
    "الحزن": ["person sitting alone hopeful sunrise", "comfort sadness prayer"],
    "حزين": ["person sitting alone hopeful sunrise", "comfort sadness prayer"],
    "الشفاء": ["healing prayer Christian", "hands praying hospital window"],
    "شفاء": ["healing prayer Christian", "hands praying hospital window"],
}

SPECIAL_IMAGE_QUERIES = [
    ("دموع", ["person praying with tears", "comfort sadness Christian prayer"]),
    ("تعب", ["person praying outdoors sunrise", "person resting mountain sunrise"]),
    ("انتظار", ["person waiting sunrise landscape", "long road sunrise"]),
    ("رجاء", ["Christian hope sunrise landscape", "sunrise golden light"]),
    ("الأمل", ["hope sunrise landscape", "sunrise golden light"]),
    ("إيمان", ["hands holding Bible sunlight", "open Bible warm light"]),
    ("الايمان", ["hands holding Bible sunlight", "open Bible warm light"]),
    ("تمسك", ["hands holding cross Bible", "hands praying Bible"]),
    ("الظروف", ["sunrise after storm landscape", "calm sea sunrise"]),
    ("محبة", ["helping hands compassion", "Christian love compassion"]),
    ("صلاة", ["person praying hands sunlight", "Christian prayer outdoors"]),
    ("الصلاة", ["person praying hands sunlight", "Christian prayer outdoors"]),
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
                path, size, layout_engine=ImageFont.Layout.RAQM
            )

    result = subprocess.run(
        ["fc-match", "-f", "%{file}", "Noto Naskh Arabic"],
        capture_output=True, text=True
    )
    path = result.stdout.strip()
    if path and Path(path).exists():
        return ImageFont.truetype(
            path, size, layout_engine=ImageFont.Layout.RAQM
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


def clean_metadata(value):
    if not value:
        return ""
    value = html.unescape(str(value))
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def http_json(url, params=None):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json"
        }
    )
    with urllib.request.urlopen(request, timeout=35) as response:
        return json.loads(response.read().decode("utf-8"))


def image_search_queries(scene_text, topic):
    text = scene_text.lower()

    for word, queries in SPECIAL_IMAGE_QUERIES:
        if word in text:
            return queries

    for arabic_word, english_queries in IMAGE_KEYWORDS.items():
        if arabic_word.lower() in text:
            return english_queries

    return [
        "Christian hope sunrise landscape",
        "person praying warm sunlight",
        "open Bible warm sunlight"
    ]


def allowed_openverse_license(license_code):
    return (license_code or "").lower() in {
        "cc0", "by", "by-sa", "pdm"
    }


# =========================================================
# IMAGE PROVIDERS
# =========================================================

def search_pixabay(query):
    if not PIXABAY_KEY:
        print("Pixabay skipped: PIXABAY_API_KEY is not configured.")
        return []

    try:
        data = http_json(
            PIXABAY_API,
            {
                "key": PIXABAY_KEY,
                "q": query,
                "image_type": "photo",
                "orientation": "vertical",
                "safesearch": "true",
                "min_width": 700,
                "per_page": 30
            }
        )

        candidates = []
        for item in data.get("hits", []):
            width = int(item.get("imageWidth", 0) or 0)
            height = int(item.get("imageHeight", 0) or 0)
            url = item.get("largeImageURL") or item.get("webformatURL")

            if width < 700 or height < 500 or not url:
                continue

            candidates.append({
                "provider": "Pixabay",
                "title": clean_metadata(item.get("tags", "Pixabay photo")),
                "author": clean_metadata(item.get("user", "Pixabay contributor")),
                "license": "Pixabay Content License",
                "source": item.get("pageURL", "https://pixabay.com/"),
                "url": url,
                "unique_id": "pixabay:" + str(item.get("id", url)),
                "width": width,
                "height": height
            })
        return candidates

        except urllib.error.HTTPError as error:
        try:
            details = error.read().decode("utf-8", errors="replace").strip()
        except Exception:
            details = "Could not read Pixabay error response."

        # Never print the request URL because it may contain the API key.
        print(f"Pixabay HTTP error: {error.code}")
        print("Pixabay response:", details[:1000])
        return []

    except Exception as error:
        print("Pixabay search failed:", type(error).__name__, str(error))
        return []


def search_openverse(query):
    try:
        data = http_json(
            OPENVERSE_API,
            {
                "q": query,
                "page_size": 30,
                "license": OPENVERSE_LICENSES,
                "mature": "false"
            }
        )

        candidates = []
        for item in data.get("results", []):
            license_code = (item.get("license") or "").lower()
            if not allowed_openverse_license(license_code):
                continue

            width = int(item.get("width", 0) or 0)
            height = int(item.get("height", 0) or 0)
            url = item.get("thumbnail") or item.get("url")

            if width < 700 or height < 500 or not url:
                continue

            candidates.append({
                "provider": "Openverse",
                "title": clean_metadata(item.get("title", "Openverse image")),
                "author": clean_metadata(item.get("creator", "Unknown creator")),
                "license": (
                    license_code.upper()
                    + (" " + str(item.get("license_version"))
                       if item.get("license_version") else "")
                ),
                "source": item.get("foreign_landing_url")
                          or item.get("detail_url")
                          or "https://openverse.org/",
                "url": url,
                "unique_id": "openverse:" + str(item.get("id", url)),
                "width": width,
                "height": height
            })
        return candidates

    except Exception as error:
        print("Openverse search failed:", str(error))
        return []


def search_commons(query):
    try:
        data = http_json(
            COMMONS_API,
            {
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": query,
                "gsrnamespace": 6,
                "gsrlimit": 30,
                "prop": "imageinfo",
                "iiprop": "url|extmetadata|size|mime",
                "iiurlwidth": 1600
            }
        )

        candidates = []
        pages = data.get("query", {}).get("pages", {})

        for page in pages.values():
            title = page.get("title", "")
            infos = page.get("imageinfo", [])
            if not title or not infos:
                continue

            info = infos[0]
            if not (info.get("mime") or "").startswith("image/"):
                continue

            width = int(info.get("width", 0) or 0)
            height = int(info.get("height", 0) or 0)
            if width < 700 or height < 500:
                continue

            ext = info.get("extmetadata", {})
            license_name = clean_metadata(
                ext.get("LicenseShortName", {}).get("value", "")
            )
            license_lower = license_name.lower()
            if not any(term in license_lower for term in (
                "public domain", "cc0", "cc by", "cc-by"
            )):
                continue

            url = info.get("thumburl") or info.get("url")
            if not url:
                continue

            candidates.append({
                "provider": "Wikimedia Commons",
                "title": clean_metadata(
                    ext.get("ObjectName", {}).get("value", "")
                    or title.replace("File:", "")
                ),
                "author": clean_metadata(
                    ext.get("Attribution", {}).get("value", "")
                    or ext.get("Artist", {}).get("value", "")
                    or "Unknown author"
                ),
                "license": license_name,
                "source": info.get(
                    "descriptionurl", "https://commons.wikimedia.org/"
                ),
                "url": url,
                "unique_id": "commons:" + title,
                "width": width,
                "height": height
            })

        return candidates

    except Exception as error:
        print("Wikimedia Commons search failed:", str(error))
        return []


# =========================================================
# CANDIDATE SCORING AND DOWNLOAD
# =========================================================

def score_candidate(candidate, query):
    title = (candidate.get("title") or "").lower()
    query_words = {
        word.lower()
        for word in re.findall(r"[a-zA-Z]{3,}", query)
    }
    title_words = set(re.findall(r"[a-zA-Z]{3,}", title))
    overlap = len(query_words & title_words)

    width = max(1, int(candidate.get("width", 1)))
    height = max(1, int(candidate.get("height", 1)))
    ratio = width / height

    # Portrait images are preferred, but landscape images remain eligible.
    aspect_score = 2 if ratio < 0.85 else (1 if ratio < 1.35 else 0)
    resolution_score = min(3, (width * height) / (1080 * 1920))
    provider_score = {
        "Pixabay": 2,
        "Openverse": 1,
        "Wikimedia Commons": 1
    }.get(candidate.get("provider"), 0)

    return overlap * 4 + aspect_score + resolution_score + provider_score


def download_candidate(candidate, destination):
    request = urllib.request.Request(
        candidate["url"],
        headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        content = response.read()

    if not content:
        raise RuntimeError("Downloaded image is empty.")

    destination.write_bytes(content)

    with Image.open(destination) as image:
        image.verify()

    with Image.open(destination) as image:
        image = image.convert("RGB")
        image = ImageOps.fit(
            image,
            (WIDTH, HEIGHT),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.42)
        )

    brightness = sum(ImageStat.Stat(image).mean) / 3
    if brightness < 42:
        raise ValueError(
            f"Image too dark (brightness {brightness:.1f})."
        )

    return image


def choose_scene_image(index, scene_text, topic, used_ids):
    queries = image_search_queries(scene_text, topic)
    all_candidates = []

    for query in queries:
        print("Searching image providers for:", query)

        # Query all providers; one provider failing does not stop the others.
        providers = (
            ("Pixabay", search_pixabay),
            ("Openverse", search_openverse),
            ("Wikimedia Commons", search_commons)
        )

        for provider_name, search_function in providers:
            results = search_function(query)
            print(f"{provider_name}: {len(results)} candidate(s)")
            all_candidates.extend(results)

    # Remove duplicates and previously used images.
    unique = {}
    for candidate in all_candidates:
        uid = candidate.get("unique_id")
        if uid and uid not in used_ids:
            unique[uid] = candidate

    ranked = sorted(
        unique.values(),
        key=lambda item: max(
            score_candidate(item, query) for query in queries
        ),
        reverse=True
    )

    print("Unique candidates after filtering:", len(ranked))

    for candidate_number, candidate in enumerate(ranked[:35], start=1):
        image_path = WORK / f"candidate_{index:02d}_{candidate_number:02d}.img"

        try:
            image = download_candidate(candidate, image_path)
            used_ids.add(candidate["unique_id"])

            print(
                "Selected:",
                candidate["provider"],
                "|",
                candidate["title"],
                "|",
                candidate["license"]
            )
            return image, candidate

        except Exception as error:
            print(
                "Candidate rejected:",
                candidate.get("provider"),
                candidate.get("title"),
                "|",
                str(error)
            )
            try:
                image_path.unlink(missing_ok=True)
            except Exception:
                pass

    print("No suitable image found. Using designed fallback background.")
    return make_fallback_background(), None


# =========================================================
# SCRIPT AND SCENES
# =========================================================

def clean_script(script):
    ignored = (
        "عنوان الريل", "وصف المنشور", "الهاشتاجات",
        "المرجع الكتابي", "هاشتاج"
    )
    lines = []

    for raw in script.splitlines():
        line = raw.strip()
        if not line or any(line.startswith(x) for x in ignored):
            continue

        line = re.sub(
            r"^(Hook|المشهد الأول|المشهد الثاني|المشهد الثالث|"
            r"المشهد الرابع|المشهد الخامس|الرسالة الختامية)\s*[:：\-]\s*",
            "", line, flags=re.IGNORECASE
        )
        line = re.sub(r"^[•\-*]\s*", "", line)
        line = re.sub(r"\([^)]*\)", "", line).strip()

        if len(line) > 2:
            lines.append(line)

    text = re.sub(r"\s+", " ", " ".join(lines)).strip()
    if len(text) < 30:
        raise ValueError("The script does not contain enough text.")
    return text


def split_scenes(text):
    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!؟?])\s+", text)
        if len(part.strip()) > 8
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

    return [
        " ".join(sentences[i:i + chunk_size])
        for i in range(0, len(sentences), chunk_size)
    ]


# =========================================================
# TEXT AND CREDITS
# =========================================================

def wrap_text(draw, text, font, max_width):
    words = text.split()
    lines = []
    current = ""

    for word in words:
        test = f"{current} {word}".strip()
        width = draw.textlength(
            test, font=font, direction="rtl", language="ar"
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


def add_scene_text(image, text):
    image = image.convert("RGBA")
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)

    overlay_draw.rectangle(
        (0, 0, WIDTH, 340), fill=(0, 0, 0, 55)
    )
    overlay_draw.rectangle(
        (0, 950, WIDTH, HEIGHT), fill=(0, 0, 0, 145)
    )

    image = Image.alpha_composite(image, overlay)
    draw = ImageDraw.Draw(image)
    font = get_font(58)
    lines = wrap_text(draw, text, font, 900)[:6]

    line_height = 100
    total_height = len(lines) * line_height
    start_y = 1110 + max(0, (520 - total_height) // 2)

    for line_index, line in enumerate(lines):
        box = draw.textbbox(
            (0, 0), line, font=font, direction="rtl", language="ar"
        )
        text_width = box[2] - box[0]
        x = (WIDTH - text_width) // 2
        y = start_y + line_index * line_height

        draw.text(
            (x + 3, y + 5), line, font=font,
            fill=(0, 0, 0, 220), direction="rtl", language="ar"
        )
        draw.text(
            (x, y), line, font=font,
            fill=(255, 250, 235, 255), direction="rtl", language="ar"
        )

    return image.convert("RGB")


def add_image_credit(image, image_info):
    if not image_info:
        return image

    image = image.convert("RGBA")
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rectangle(
        (0, 1835, WIDTH, HEIGHT), fill=(0, 0, 0, 155)
    )

    font = get_credit_font(17)
    provider = clean_metadata(image_info.get("provider", "Image source"))
    title = clean_metadata(image_info.get("title", "Image"))[:55]
    author = clean_metadata(image_info.get("author", "Unknown creator"))[:38]
    license_name = clean_metadata(image_info.get("license", "License"))[:30]

    line_one = f"{provider}: {title} | {author}"
    line_two = f"License: {license_name}"

    draw.text(
        (WIDTH // 2, 1868), line_one, font=font,
        fill=(255, 255, 255, 245), anchor="mm"
    )
    draw.text(
        (WIDTH // 2, 1908), line_two, font=font,
        fill=(245, 230, 205, 245), anchor="mm"
    )

    return image.convert("RGB")


# =========================================================
# FALLBACK BACKGROUND
# =========================================================

def make_fallback_background():
    image = Image.new("RGB", (WIDTH, HEIGHT))
    pixels = image.load()
    top = (24, 42, 68)
    bottom = (190, 142, 82)

    for y in range(HEIGHT):
        ratio = y / max(1, HEIGHT - 1)
        color = tuple(
            int(top[c] * (1 - ratio) + bottom[c] * ratio)
            for c in range(3)
        )
        for x in range(WIDTH):
            pixels[x, y] = color

    return image


# =========================================================
# VIDEO RENDERING
# =========================================================

def render_scene(image_path, duration, output_path):
    frames = max(1, int(math.ceil(duration * FPS)))
    video_filter = (
        "zoompan=z='min(zoom+0.00035,1.08)':"
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
    topic = os.environ.get(
        "REEL_TOPIC", "رسالة رجاء وأمل"
    ).strip()
    script = os.environ.get("REEL_SCRIPT", "").strip()
    duration = int(os.environ.get("REEL_DURATION", "35"))

    if not script:
        raise ValueError("REEL_SCRIPT is empty.")
    if duration < 10 or duration > 180:
        raise ValueError("Video duration must be between 10 and 180 seconds.")

    check_arabic_support()

    print("=" * 55)
    print("CHRISTIAN REELS FACTORY - MULTI SOURCE")
    print("Topic:", topic)
    print("Duration:", duration)
    print("Pixabay key configured:", bool(PIXABAY_KEY))
    print("Providers: Pixabay, Openverse, Wikimedia Commons")
    print("=" * 55)

    clean_text = clean_script(script)
    scenes = split_scenes(clean_text)
    if not scenes:
        raise RuntimeError("No scenes were generated.")

    print("Number of scenes:", len(scenes))

    used_ids = set()
    scene_duration = duration / len(scenes)
    scene_files = []

    for pattern in ("scene_*.mp4", "scene_*.jpg", "candidate_*", "source_*"):
        for old_file in WORK.glob(pattern):
            if old_file.is_file():
                old_file.unlink()

    for index, scene_text in enumerate(scenes, start=1):
        print()
        print("-" * 55)
        print(f"Rendering scene {index}/{len(scenes)}")
        print(scene_text)

        image, image_info = choose_scene_image(
            index, scene_text, topic, used_ids
        )

        image = add_scene_text(image, scene_text)
        image = add_image_credit(image, image_info)

        image_path = WORK / f"scene_{index:02d}.jpg"
        video_path = WORK / f"scene_{index:02d}.mp4"

        image.save(image_path, "JPEG", quality=94)
        render_scene(image_path, scene_duration, video_path)
        scene_files.append(video_path)

    concat_file = WORK / "concat_list.txt"
    with concat_file.open("w", encoding="utf-8") as file:
        for scene_file in scene_files:
            safe_path = str(scene_file.resolve()).replace("'", "'\\''")
            file.write(f"file '{safe_path}'\n")

    output_path = OUTPUT / "christian_reel.mp4"
    output_path.unlink(missing_ok=True)

    print()
    print("Combining all scenes...")

    run([
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-r", str(FPS),
        "-an",
        "-movflags", "+faststart",
        str(output_path)
    ])

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("Final video was not created correctly.")

    print()
    print("=" * 55)
    print("VIDEO CREATED SUCCESSFULLY")
    print("Output:", output_path)
    print("Size:", output_path.stat().st_size, "bytes")
    print("=" * 55)


if __name__ == "__main__":
    main()
