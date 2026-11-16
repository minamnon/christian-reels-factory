import os
import json
import base64
import urllib.parse
import urllib.request
import urllib.error
import mimetypes
from PIL import Image
import time
from pathlib import Path

MODEL = "gemini-3.8-flash"
ROOT = Path("artifacts/gemini-vision-test")
ROOT.mkdir(parents=True, exist_ok=True)

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
PIXABAY_KEY = os.environ.get("PIXABAY_API_KEY", "").strip()

SCENES = [
    {
        "id": "marital_apology",
        "title": "زوج يحاول الاعتذار لزوجته بعد خلاف",
        "brief": (
            "A realistic scene showing a husband sincerely apologizing "
            "to his wife after an argument at home. Both adults are visible. "
            "The image should communicate the interaction and relationship, "
            "not merely show a random happy couple or wedding."
        ),
        "query": "couple serious conversation at home"
    },
    {
        "id": "christian_prayer",
        "title": "شخص مسيحي يصلي داخل كنيسة",
        "brief": (
            "A realistic Christian scene showing one person praying inside "
            "a church. The church interior and prayer action should be visible. "
            "A generic portrait, landscape, or unrelated religious decoration "
            "is not a sufficient match."
        ),
        "query": "person praying inside church"
    }
]

def request_json(url, headers=None, payload=None, timeout=60):
    data = None
    hdrs = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))

def safe_error(exc):
    status = getattr(exc, "code", None)
    label = type(exc).__name__
    return f"{label} (HTTP {status})" if status else label


def search_pixabay(query):
    params = {
        "key": PIXABAY_KEY,
        "q": query,
        "image_type": "photo",
        "orientation": "vertical",
        "safesearch": "true",
        "per_page": 12,
        "min_width": 500
    }
    url = "https://pixabay.com/api/?" + urllib.parse.urlencode(params)
    data = request_json(url, {"User-Agent": "ChristianReelsFactory-VisionTest/1.0"})
    results = []
    for item in data.get("hits", []):
        image_url = item.get("largeImageURL") or item.get("webformatURL")
        if not image_url:
            continue
        results.append({
            "id": item.get("id"),
            "title": item.get("tags", ""),
            "page_url": item.get("pageURL", ""),
            "image_url": image_url,
            "width": item.get("imageWidth"),
            "height": item.get("imageHeight")
        })
    return results

def download_image(url, path):
    req = urllib.request.Request(
        url, headers={"User-Agent": "ChristianReelsFactory-VisionTest/1.0"}
    )
    with urllib.request.urlopen(req, timeout=60) as res:
        content = res.read(8 * 1024 * 1024 + 1)
        content_type = res.headers.get("Content-Type", "").split(";")[0].lower()
    if len(content) > 8 * 1024 * 1024:
        raise RuntimeError("Image exceeds 8 MB")
    if not content or not content_type.startswith("image/"):
        raise RuntimeError("Downloaded content is not an image")
    ext = mimetypes.guess_extension(content_type) or ".img"
    if ext == ".jpe":
        ext = ".jpg"
    path = path.with_suffix(ext)
    path.write_bytes(content)
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            if width < 300 or height < 300:
                raise RuntimeError("Image dimensions are too small")
    except Exception:
        path.unlink(missing_ok=True)
        raise RuntimeError("Downloaded file is not a valid usable image")
    return path, content, content_type

def evaluate_image(scene, image_bytes, mime_type):
    prompt = f"""
You are a strict visual quality evaluator for vertical social video scenes.

Target scene:
{scene['brief']}

Inspect the actual image pixels. Do NOT trust its filename, title, tags,
search query, or provider metadata.

Return JSON only with these fields:
{{
  "match": true or false,
  "score": integer from 0 to 10,
  "visible_people": "brief description",
  "visible_action": "what is actually happening",
  "relationship": "what relationship is visually supported",
  "setting": "where the scene appears to take place",
  "emotion": "visible emotional tone",
  "main_subject_clear": true or false,
  "vertical_composition": "good, acceptable, or poor",
  "unwanted_elements": ["..."],
  "reason": "specific explanation of the decision"
}}

Rules:
- match=true only if the actual visible action, people/relationship, and setting
  substantially fit the target scene.
- A similar keyword, mood, attractive photo, or generic portrait is NOT enough.
- If the key action or relationship cannot be confirmed visually, match=false.
- Do not infer details that cannot be seen.
- Score 8-10: strong direct match.
- Score 5-7: partial match, not acceptable as a final scene image.
- Score 0-4: wrong or unrelated.
"""
    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": prompt},
                {"inlineData": {
                    "mimeType": mime_type,
                    "data": base64.b64encode(image_bytes).decode("ascii")
                }}
            ]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json"
        }
    }
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"models/{MODEL}:generateContent"
    )
    data = request_json(
        url,
        {"x-goog-api-key": GEMINI_KEY},
        payload,
        timeout=120
    )
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    result = json.loads(text)
    usage = data.get("usageMetadata", {})
    return result, usage

def main():
    if not GEMINI_KEY:
        raise RuntimeError("GEMINI_API_KEY is missing from workflow environment")
    if not PIXABAY_KEY:
        raise RuntimeError("PIXABAY_API_KEY is missing from workflow environment")

    report = {
        "model": MODEL,
        "test": "real_image_pixel_inspection",
        "scenes": [],
        "errors": [],
        "summary": {
            "images_downloaded": 0,
            "vision_calls": 0,
            "strong_matches": 0,
            "rejected": 0,
            "fallbacks": 0
        }
    }

    for scene in SCENES:
        print(f"\n===== {scene['id']} =====")
        scene_dir = ROOT / scene["id"]
        scene_dir.mkdir(parents=True, exist_ok=True)
        scene_report = {
            "scene_id": scene["id"],
            "scene_title": scene["title"],
            "visual_brief": scene["brief"],
            "search_query": scene["query"],
            "candidates": [],
            "selected": None,
            "fallback": False
        }

        try:
            candidates = search_pixabay(scene["query"])[:3]
        except Exception as exc:
            report["errors"].append(
                {"scene": scene["id"], "stage": "pixabay_search",
                 "error": safe_error(exc)}
            )
            candidates = []

        for index, candidate in enumerate(candidates, 1):
            item = {
                "candidate_number": index,
                "provider": "Pixabay",
                "title": candidate["title"],
                "source_page": candidate["page_url"],
                "source_dimensions": {
                    "width": candidate["width"],
                    "height": candidate["height"]
                },
                "downloaded_file": None,
                "vision": None,
                "status": "not_evaluated"
            }
            try:
                path, raw, mime = download_image(
                    candidate["image_url"],
                    scene_dir / f"candidate_{index}"
                )
                item["downloaded_file"] = str(path)
                item["downloaded_bytes"] = len(raw)
                report["summary"]["images_downloaded"] += 1

                vision, usage = evaluate_image(scene, raw, mime)
                item["vision"] = vision
                item["usage_metadata"] = usage
                report["summary"]["vision_calls"] += 1

                if vision.get("match") is True and int(vision.get("score", 0)) >= 8:
                    item["status"] = "strong_match"
                    report["summary"]["strong_matches"] += 1
                else:
                    item["status"] = "rejected"
                    report["summary"]["rejected"] += 1

                print(
                    f"Candidate {index}: {item['status']} | "
                    f"score={vision.get('score')} | "
                    f"{str(vision.get('reason', ''))[:180]}"
                )

            except Exception as exc:
                item["status"] = "error"
                item["error"] = safe_error(exc)
                report["errors"].append({
                    "scene": scene["id"],
                    "candidate": index,
                    "error": safe_error(exc)
                })
                print(f"Candidate {index}: ERROR - {type(exc).__name__}")

            scene_report["candidates"].append(item)

        accepted = [
            item for item in scene_report["candidates"]
            if item["status"] == "strong_match"
        ]
        if accepted:
            scene_report["selected"] = max(
                accepted,
                key=lambda x: int(x["vision"].get("score", 0))
            )
        else:
            scene_report["fallback"] = True
            report["summary"]["fallbacks"] += 1

        report["scenes"].append(scene_report)

    report_path = ROOT / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    summary = [
        f"Model: {MODEL}",
        f"Images downloaded: {report['summary']['images_downloaded']}",
        f"Vision calls: {report['summary']['vision_calls']}",
        f"Strong matches: {report['summary']['strong_matches']}",
        f"Rejected: {report['summary']['rejected']}",
        f"Fallback scenes: {report['summary']['fallbacks']}",
        f"Errors: {len(report['errors'])}",
        "",
        "Scene decisions:"
    ]
    for scene in report["scenes"]:
        selected = scene["selected"]
        if selected:
            summary.append(
                f"- {scene['scene_id']}: SELECTED "
                f"(score {selected['vision'].get('score')}/10) - "
                f"{selected['title']}"
            )
        else:
            summary.append(f"- {scene['scene_id']}: FALLBACK (no confirmed match)")

    (ROOT / "summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print("\n" + "\n".join(summary))
    print(f"\nReport saved: {report_path}")

    if report["summary"]["vision_calls"] == 0:
        raise RuntimeError("No successful Gemini Vision calls; inspect report errors")

if __name__ == "__main__":
    main()
