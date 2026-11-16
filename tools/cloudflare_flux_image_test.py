import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from worker.render.image_generation import generate_scene_image


OUT = ROOT / "artifacts" / "cloudflare-flux-test"
OUT.mkdir(parents=True, exist_ok=True)

SCENES = [
    {
        "name": "christian_prayer",
        "topic": "Christian prayer",
        "prompt": (
            "A person quietly praying inside a beautiful traditional "
            "Christian church, hands gently raised in prayer, wooden "
            "pews, a clearly recognizable Christian cross in the "
            "background, warm natural window light, peaceful emotion."
        )
    },
    {
        "name": "marital_apology",
        "topic": "marital reconciliation",
        "prompt": (
            "An Egyptian married couple in their modern modest home "
            "having an emotional reconciliation moment. The husband "
            "sincerely apologizes while speaking gently, his wife "
            "listens with a serious but emotional expression. Both "
            "adults are clearly visible, with believable body language."
        )
    }
]

results = []

for index, scene in enumerate(SCENES, start=1):
    print(f"===== {scene['name']} =====")

    image = generate_scene_image(
        scene_text=scene["prompt"],
        topic=scene["topic"],
        scene_number=index
    )

    path = OUT / (scene["name"] + ".jpg")
    image.save(path, "JPEG", quality=95)

    results.append({
        "scene": scene["name"],
        "status": "success",
        "file": str(path.relative_to(ROOT)),
        "width": image.width,
        "height": image.height,
        "bytes": path.stat().st_size
    })

report = {
    "model": "@cf/black-forest-labs/flux-1-schnell",
    "images_requested": len(SCENES),
    "target_size": "1080x1920",
    "results": results
}

(OUT / "report.json").write_text(
    json.dumps(report, indent=2),
    encoding="utf-8"
)

print(json.dumps(report, indent=2))
