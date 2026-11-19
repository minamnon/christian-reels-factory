import base64
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from io import BytesIO

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

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

    # Blurred, slightly darkened copy fills the vertical canvas.
    background = ImageOps.fit(
        image,
        (WIDTH, HEIGHT),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.42)
    )
    background = background.filter(
        ImageFilter.GaussianBlur(radius=36)
    )
    background = ImageEnhance.Brightness(background).enhance(0.6)

    # Preserve the complete generated image in the foreground.
    foreground = ImageOps.contain(
        image,
        (WIDTH, HEIGHT),
        method=Image.Resampling.LANCZOS
    )

    # Feather the top/bottom edges so no hard seam shows.
    mask = Image.new("L", foreground.size, 255)
    mask_draw = ImageDraw.Draw(mask)
    fade = min(64, foreground.height // 6)
    for i in range(fade):
        value = int(255 * i / fade)
        mask_draw.line((0, i, foreground.width, i), fill=value)
        mask_draw.line(
            (0, foreground.height - 1 - i,
             foreground.width, foreground.height - 1 - i),
            fill=value
        )

    x = (WIDTH - foreground.width) // 2
    y = (HEIGHT - foreground.height) // 2

    background.paste(foreground, (x, y), mask)

    return background


# =========================================================
# OPTIONAL: FLUX.2 klein (true 9:16 + character reference images)
# Enabled per reel with  "image_model": "klein"  in the scene plan
# (or REEL_IMAGE_MODEL=klein). Default stays FLUX.1 schnell, and any
# klein failure falls back to schnell automatically.
# =========================================================

KLEIN_MODELS = {
    "klein": "@cf/black-forest-labs/flux-2-klein-9b",
    "klein-9b": "@cf/black-forest-labs/flux-2-klein-9b",
    "klein-4b": "@cf/black-forest-labs/flux-2-klein-4b",
}
KLEIN_WIDTH = 1024
KLEIN_HEIGHT = 1792   # 9:16, inside the 256-1920 range, multiple of 16
REF_MAX_SIDE = 480    # reference images must be smaller than 512x512
_CHAR_REFS = {}       # character key -> PNG bytes (one portrait per reel)


def _plan_image_model(plan):
    name = str(
        (plan or {}).get("image_model")
        or os.environ.get("REEL_IMAGE_MODEL", "")
    ).strip().lower()
    return KLEIN_MODELS.get(name)


def _multipart(fields, files):
    boundary = "----crf" + uuid.uuid4().hex
    body = bytearray()
    for name, value in fields.items():
        body += (
            f"--{boundary}\r\nContent-Disposition: form-data; "
            f"name=\"{name}\"\r\n\r\n{value}\r\n"
        ).encode("utf-8")
    for name, (filename, data, content_type) in files.items():
        body += (
            f"--{boundary}\r\nContent-Disposition: form-data; "
            f"name=\"{name}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8") + data + b"\r\n"
    body += f"--{boundary}--\r\n".encode("utf-8")
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def _decode_image_response(raw):
    if raw[:1] == b"{":
        data = json.loads(raw)
        if data.get("success") is False:
            raise RuntimeError("Cloudflare FLUX.2 returned success=false.")
        result = data.get("result")
        encoded = result.get("image") if isinstance(result, dict) else None
        if not encoded:
            raise RuntimeError("Cloudflare FLUX.2 response has no image.")
        return base64.b64decode(encoded)
    return raw  # some models return the image bytes directly


def _klein_request(model, prompt, refs, width, height):
    account_id, token = _get_credentials()
    url = (
        "https://api.cloudflare.com/client/v4/accounts/"
        + account_id + "/ai/run/" + model
    )
    files = {
        f"input_image_{i}": (f"ref{i}.png", data, "image/png")
        for i, data in enumerate(refs[:4])
    }
    body, content_type = _multipart(
        {"prompt": prompt, "width": str(width), "height": str(height)},
        files,
    )

    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        request = urllib.request.Request(
            url, data=body, method="POST",
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": content_type,
            },
        )
        try:
            with urllib.request.urlopen(
                request, timeout=REQUEST_TIMEOUT
            ) as response:
                return _decode_image_response(response.read())
        except urllib.error.HTTPError as error:
            last_error = RuntimeError(
                f"Cloudflare FLUX.2 HTTP error: {error.code}"
            )
            if error.code not in (408, 429, 500, 502, 503, 504) \
                    or attempt == MAX_ATTEMPTS:
                raise last_error from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last_error = RuntimeError(
                "Cloudflare FLUX.2 connection failed: "
                + type(error).__name__
            )
            if attempt == MAX_ATTEMPTS:
                raise last_error from None
        time.sleep(8 * attempt)
    raise last_error or RuntimeError("Cloudflare FLUX.2 generation failed.")


def _to_reference_png(image_bytes):
    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    image = ImageOps.contain(image, (REF_MAX_SIDE, REF_MAX_SIDE))
    out = BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def _ensure_character_refs(model, plan, keys):
    profile = get_profile(plan.get("profile"))
    characters = plan.get("characters") or {}
    for key in keys:
        description = characters.get(key)
        if key in _CHAR_REFS or not description:
            continue
        prompt = " ".join(" ".join(str(p).split()) for p in (
            "Head-and-shoulders portrait photograph of one person, "
            "looking at the camera, soft even light, plain neutral "
            "background, natural expression.",
            description,
            profile["style"],
            profile["rules"],
        ))
        try:
            raw = _klein_request(model, prompt, [], 1024, 1024)
            _CHAR_REFS[key] = _to_reference_png(raw)
            print(f"Character reference ready: {key}")
        except Exception as error:
            print(f"Character reference failed for {key}:",
                  type(error).__name__, str(error)[:120])


def _build_klein_prompt(plan, scene_index, ref_keys):
    profile = get_profile(plan.get("profile"))
    scene = plan["scenes"][scene_index]
    characters = plan.get("characters") or {}

    parts = [str(scene["visual"])]
    for number, key in enumerate(ref_keys):
        parts.append(
            f"Reference image {number} is the character {key}: keep exactly "
            "the same face, age, hair, beard and clothes in this scene."
        )
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
            f"Scene {scene_index + 1} prompt is {len(prompt)} characters."
        )
    return prompt


def _generate_with_klein(model, plan, scene_index, scene_number):
    keys = list(plan["scenes"][scene_index].get("characters") or [])
    _ensure_character_refs(model, plan, keys)
    ref_keys = [k for k in keys if k in _CHAR_REFS][:4]
    prompt = _build_klein_prompt(plan, scene_index, ref_keys)
    print(f"FLUX.2 prompt (scene {scene_number}):", prompt)
    print(f"Generating scene {scene_number} with {model} "
          f"({KLEIN_WIDTH}x{KLEIN_HEIGHT}, {len(ref_keys)} reference images)")

    raw = _klein_request(
        model, prompt, [_CHAR_REFS[k] for k in ref_keys],
        KLEIN_WIDTH, KLEIN_HEIGHT,
    )
    image = Image.open(BytesIO(raw))
    image.load()
    image = ImageOps.fit(
        image.convert("RGB"), (WIDTH, HEIGHT),
        method=Image.Resampling.LANCZOS, centering=(0.5, 0.45),
    )
    print(f"Scene {scene_number}: true 9:16 image -> "
          f"{image.width}x{image.height}")
    return image


def generate_scene_image(scene_text, topic, scene_number=1,
                         scene_plan=None, scene_index=None):
    klein_model = _plan_image_model(scene_plan)
    if klein_model and scene_plan is not None and scene_index is not None:
        try:
            return _generate_with_klein(
                klein_model, scene_plan, scene_index, scene_number
            )
        except Exception as error:
            print("FLUX.2 klein failed:", type(error).__name__,
                  str(error)[:160], "- falling back to FLUX.1 schnell.")

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

