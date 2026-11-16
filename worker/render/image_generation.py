import base64
import json
import os
import time
import urllib.error
import urllib.request
from io import BytesIO

from PIL import Image, ImageFilter, ImageOps

try:
    from content_profiles import get_profile
except ModuleNotFoundError as error:
    if error.name != "content_profiles":
        raise
    from worker.render.content_profiles import get_profile



MODEL = "@cf/black-forest-labs/flux-1-schnell"
WIDTH = 1080
HEIGHT = 1920
STEPS = 4
REQUEST_TIMEOUT = 300
MAX_ATTEMPTS = 3


def build_image_prompt(scene_text, topic):
    scene = " ".join(str(scene_text).split())
    subject = " ".join(str(topic).split())

    if not scene:
        raise ValueError("Scene description is empty.")

    prefix = (
        "Create one highly realistic cinematic documentary photograph "
        "for a professional vertical short-form video. "
        "Depict the exact described event, people, actions, emotions, "
        "and relationships. Do not substitute a generic symbolic image. "
        "Use realistic human faces, anatomically correct hands, "
        "believable body language, authentic environments, "
        "cinematic natural lighting and professional photography. "
        "Compose the complete important subjects near the center, "
        "with enough space around them for vertical presentation. "
    )

    scene_label = "EXACT SCENE: "
    context_label = ". REEL CONTEXT: "
    ending = ". "
    suffix = "No text, letters, subtitles, logos or watermarks."

    fixed_length = (
        len(prefix)
        + len(scene_label)
        + len(context_label)
        + len(ending)
        + len(suffix)
    )

    available = 2048 - fixed_length

    if available < 1:
        raise ValueError("Fixed image prompt instructions exceed the limit.")

    # Give priority to the exact scene, then use remaining space for context.
    scene_part = scene[:int(available * 0.8)]
    remaining = available - len(scene_part)
    topic_part = subject[:remaining]

    # If the scene itself is short, use the extra space for reel context.
    remaining -= len(topic_part)
    if remaining > 0 and len(scene_part) < len(scene):
        extra_scene = scene[len(scene_part):len(scene_part) + remaining]
        scene_part += extra_scene

    prompt = (
        prefix
        + scene_label
        + scene_part
        + context_label
        + topic_part
        + ending
        + suffix
    )

    if len(prompt) > 2048:
        raise RuntimeError("Image prompt exceeded the 2048-character limit.")

    return prompt


def build_plan_prompt(plan, scene_index):
    profile = get_profile(plan.get("profile"))
    scene = plan["scenes"][scene_index]
    characters = plan.get("characters") or {}

    parts = [str(scene["visual"])]
    for key in scene.get("characters") or []:
        description = characters.get(key)
        if description:
            parts.append(f"Character {key}: {description}")
    setting = plan.get("setting")
    if setting:
        parts.append(f"Setting: {setting}")
    parts.append(profile["style"])
    parts.append(profile["rules"])

    prompt = " ".join(" ".join(str(p).split()) for p in parts if p)
    if len(prompt) > 2048:
        raise RuntimeError(
            f"Scene {scene_index + 1} prompt is {len(prompt)} characters; limit is 2048."
        )
    return prompt


def _get_credentials():
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()

    if not account_id:
        raise RuntimeError("CLOUDFLARE_ACCOUNT_ID is missing.")

    if not token:
        raise RuntimeError("CLOUDFLARE_API_TOKEN is missing.")

    return account_id, token


def _request_image(prompt):
    account_id, token = _get_credentials()

    url = (
        "https://api.cloudflare.com/client/v4/accounts/"
        + account_id
        + "/ai/run/"
        + MODEL
    )

    payload = json.dumps({
        "prompt": prompt,
        "steps": STEPS
    }).encode("utf-8")

    last_error = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        request = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json"
            },
            method="POST"
        )

        try:
            with urllib.request.urlopen(
                request, timeout=REQUEST_TIMEOUT
            ) as response:
                data = json.loads(response.read())

            if not data.get("success"):
                raise RuntimeError(
                    "Cloudflare FLUX returned success=false."
                )

            encoded = data.get("result", {}).get("image")

            if not encoded:
                raise RuntimeError(
                    "Cloudflare FLUX response has no result.image."
                )

            return base64.b64decode(encoded, validate=True)

        except urllib.error.HTTPError as error:
            last_error = RuntimeError(
                f"Cloudflare FLUX HTTP error: {error.code}"
            )

            retryable = error.code in (
                408, 429, 500, 502, 503, 504
            )

            if not retryable or attempt == MAX_ATTEMPTS:
                raise last_error from None

        except (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError
        ) as error:
            last_error = RuntimeError(
                "Cloudflare FLUX connection failed: "
                + type(error).__name__
            )

            if attempt == MAX_ATTEMPTS:
                raise last_error from None

        if attempt < MAX_ATTEMPTS:
            delay = 8 * attempt
            print(
                f"FLUX retry {attempt + 1}/{MAX_ATTEMPTS} "
                f"after {delay}s"
            )
            time.sleep(delay)

    raise last_error or RuntimeError("Cloudflare FLUX generation failed.")


def _make_portrait_canvas(image):
    image = image.convert("RGB")

    # Blurred version fills the vertical canvas without black bars.
    background = ImageOps.fit(
        image,
        (WIDTH, HEIGHT),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.42)
    )
    background = background.filter(
        ImageFilter.GaussianBlur(radius=36)
    )

    # Preserve the complete generated image in the foreground.
    foreground = ImageOps.contain(
        image,
        (WIDTH, HEIGHT),
        method=Image.Resampling.LANCZOS
    )

    x = (WIDTH - foreground.width) // 2
    y = (HEIGHT - foreground.height) // 2

    background.paste(foreground, (x, y))

    return background


def generate_scene_image(scene_text, topic, scene_number=1,
                         scene_plan=None, scene_index=None):
    if scene_plan is not None and scene_index is not None:
        prompt = build_plan_prompt(scene_plan, scene_index)
        print(f"FLUX prompt (scene {scene_number}):", prompt)
    else:
        prompt = build_image_prompt(scene_text, topic)

    print(
        f"Generating scene {scene_number} with "
        f"{MODEL} ({STEPS} steps)"
    )

    image_bytes = _request_image(prompt)

    try:
        image = Image.open(BytesIO(image_bytes))
        image.verify()

        image = Image.open(BytesIO(image_bytes))
        image.load()
        image = image.convert("RGB")

    except Exception as error:
        raise RuntimeError(
            "Cloudflare FLUX returned an invalid image: "
            + type(error).__name__
        ) from None

    original_size = image.size
    image = _make_portrait_canvas(image)

    print(
        f"Scene {scene_number}: "
        f"{original_size[0]}x{original_size[1]} "
        f"-> {image.width}x{image.height} "
        "(full image preserved)"
    )

    return image
