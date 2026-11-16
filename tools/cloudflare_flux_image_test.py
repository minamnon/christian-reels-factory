import os
import json
import base64
import time
import urllib.request
import urllib.error
from pathlib import Path
from io import BytesIO
from PIL import Image

MODEL = "@cf/black-forest-labs/flux-1-schnell"
ACCOUNT = os.environ["CLOUDFLARE_ACCOUNT_ID"]
TOKEN = os.environ["CLOUDFLARE_API_TOKEN"]

OUT = Path("artifacts/cloudflare-flux-test")
OUT.mkdir(parents=True, exist_ok=True)

SCENES = [
    {
        "name": "christian_prayer",
        "prompt": (
            "Photorealistic cinematic documentary photograph, vertical "
            "portrait composition. A person quietly praying inside a "
            "beautiful traditional Christian church, hands gently clasped, "
            "wooden pews, a clearly recognizable Christian cross in the "
            "background, warm natural window light, authentic peaceful "
            "emotion, realistic human anatomy, detailed face and hands, "
            "professional photography, no text, no watermark."
        )
    },
    {
        "name": "marital_apology",
        "prompt": (
            "Photorealistic cinematic documentary photograph, vertical "
            "portrait composition. An Egyptian married couple in their "
            "modern modest home having an emotional reconciliation moment. "
            "The husband sincerely apologizes while speaking gently, "
            "his wife listens with serious but emotional expression, "
            "natural believable body language, both adults clearly visible, "
            "authentic Egyptian appearance, realistic home environment, "
            "soft natural window lighting, professional photography, "
            "no text, no watermark."
        )
    }
]

def generate(scene):
    url = (
        "https://api.cloudflare.com/client/v4/accounts/"
        + ACCOUNT + "/ai/run/" + MODEL
    )

    payload = json.dumps({
        "prompt": scene["prompt"],
        "steps": 4
    }).encode()

    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": "Bearer " + TOKEN,
            "Content-Type": "application/json"
        },
        method="POST"
    )

    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                data = json.loads(response.read())

            if not data.get("success"):
                raise RuntimeError("Cloudflare API returned success=false")

            encoded = data.get("result", {}).get("image")
            if not encoded:
                raise RuntimeError("No image field in API response")

            image_bytes = base64.b64decode(encoded, validate=True)

            image = Image.open(BytesIO(image_bytes))
            image.verify()

            image = Image.open(BytesIO(image_bytes))
            image.load()

            path = OUT / (scene["name"] + ".jpg")
            image.convert("RGB").save(path, "JPEG", quality=95)

            return {
                "scene": scene["name"],
                "status": "success",
                "file": str(path),
                "width": image.width,
                "height": image.height,
                "bytes": path.stat().st_size
            }

        except urllib.error.HTTPError as exc:
            print(f"{scene['name']}: HTTP {exc.code}")
            if exc.code not in (429, 500, 502, 503, 504):
                raise
            if attempt == 2:
                raise
            time.sleep(10 * (attempt + 1))

        except Exception as exc:
            print(f"{scene['name']}: {type(exc).__name__}: {exc}")
            raise

results = []

for scene in SCENES:
    print(f"Generating: {scene['name']}")
    results.append(generate(scene))
    print(f"Completed: {scene['name']}")

report = {
    "model": MODEL,
    "images_requested": len(SCENES),
    "results": results
}

(OUT / "report.json").write_text(
    json.dumps(report, indent=2),
    encoding="utf-8"
)

print(json.dumps(report, indent=2))
