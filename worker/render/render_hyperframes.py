"""
Experimental entry point: generate images + voice with the existing pipeline,
then assemble the final Reel using HyperFrames instead of FFmpeg zoompan/concat.

Triggered by the workflow render-reel-hyperframes-test.yml
or by setting REEL_RENDERER=hyperframes when calling the normal render.

This file intentionally re-uses functions from render.py and does not
duplicate image or voice generation logic.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

# Make local imports work the same way as render.py
sys.path.insert(0, str(Path(__file__).resolve().parent))

import render as base
import voice
from hyperframes_compose import (
    write_hyperframes_project,
    render_with_hyperframes,
)

WORK = base.WORK
OUTPUT = base.OUTPUT
FPS = base.FPS


def main():
    topic = os.environ.get("REEL_TOPIC", "رسالة رجاء وأمل").strip()
    script = os.environ.get("REEL_SCRIPT", "").strip()
    # Dispatch forms are single-line; accept literal \n as line breaks.
    script = script.replace("\\n", "\n")
    duration = int(os.environ.get("REEL_DURATION", "35"))

    if not script:
        raise ValueError("REEL_SCRIPT is empty.")
    if duration < 10 or duration > 180:
        raise ValueError("Video duration must be between 10 and 180 seconds.")

    base.check_arabic_support()

    print("=" * 55)
    print("CHRISTIAN REELS FACTORY — HyperFrames experimental path")
    print("Topic:", topic)
    print("Duration:", duration)
    print("=" * 55)

    dialogue = voice.parse_dialogue(script)
    scene_groups = None
    if dialogue:
        clean_text = " ".join(text for _, text in dialogue)
        count = min(6, max(3, math.ceil(len(dialogue) / 2)))
        count = min(count, len(dialogue))
        size = math.ceil(len(dialogue) / count)
        scene_groups = [
            list(range(i, min(i + size, len(dialogue))))
            for i in range(0, len(dialogue), size)
        ]
        scenes = [
            " ".join(dialogue[i][1] for i in group)
            for group in scene_groups
        ]
    else:
        clean_text = base.clean_script(script)
        scenes = base.split_scenes(clean_text)

    plan = None
    try:
        plan = base.load_scene_plan()
    except Exception as plan_err:
        print("Scene plan ignored (invalid JSON or schema):",
              type(plan_err).__name__, str(plan_err)[:200])
        plan = None
    # Parity with render.py: apply the plan's language settings.
    # Default stays Arabic (RTL fonts, ar-EG voices); only an explicit
    # "language": "en" in the plan switches anything.
    base.apply_language(plan)
    if plan:
        scenes = [
            voice.strip_speaker_labels(str(s["narration"]).strip())
            for s in plan["scenes"]
        ]
        scene_groups = (
            voice.assign_lines_to_scenes(dialogue, scenes)
            if dialogue else None
        )
        print("Scene plan loaded. Profile:", plan.get("profile", "general"))
        try:
            from image_generation import prepare_character_references
            prepare_character_references(plan)
        except Exception as ref_err:
            print("Character reference preparation skipped:",
                  type(ref_err).__name__, str(ref_err)[:120])

    if not scenes:
        raise RuntimeError("No scenes were generated.")

    print("Number of scenes:", len(scenes))

    # ----- Voice (unchanged) -----
    voice_path = None
    line_seconds = None
    try:
        if dialogue:
            result = voice.generate_dialogue(
                dialogue, WORK, script=script, plan=plan)
            if result:
                voice_path, line_seconds = result
        if not voice_path:
            voice_path = voice.generate_voice(clean_text, WORK)
        if voice_path:
            voice_seconds = voice.audio_duration(voice_path)
            total_seconds = voice_seconds + 0.8
            print(
                f"Voice-over: {voice_seconds:.1f}s "
                f"(requested {duration}s). Video will be {total_seconds:.1f}s."
            )
    except Exception as error:
        print("Voice-over unusable:", type(error).__name__, str(error)[:200])
        voice_path = None

    if not voice_path:
        total_seconds = float(duration)
        print("Rendering a silent video.")

    weights = [max(1, len(scene)) for scene in scenes]
    scene_durations = [
        total_seconds * weight / sum(weights) for weight in weights
    ]
    if voice_path and line_seconds and scene_groups:
        scene_durations = [
            sum(line_seconds[i] for i in group) for group in scene_groups
        ]
        scene_durations[-1] += max(0.0, total_seconds - sum(scene_durations))

    # ----- Subtitles (reuse existing PNG generator) -----
    sub_events = []
    if voice_path and line_seconds and scene_groups and dialogue:
        cursor = 0.0
        for number, (_, line_text) in enumerate(dialogue):
            end = cursor + line_seconds[number]
            png = WORK / f"sub_{number:02d}.png"
            base.make_subtitle_png(line_text).save(png)
            sub_events.append((png, cursor, end))
            cursor = end

    # ----- Images (unchanged generation) -----
    used_ids = set()
    scene_image_paths = []
    for index, scene_text in enumerate(scenes, start=1):
        print(f"\nRendering scene {index}/{len(scenes)}")
        print(scene_text[:120])
        image, image_info = base.choose_scene_image(
            index, scene_text, topic, used_ids=used_ids,
            scene_plan=plan, scene_index=index - 1,
        )
        if image_info and image_info.get("id"):
            used_ids.add(image_info["id"])
        # Bake scene text onto the image only when there are no timed
        # subtitle PNGs (parity with render.py — avoids double text),
        # and never swallow a rendering failure silently.
        if not sub_events:
            try:
                image = base.add_scene_text(image, scene_text)
            except Exception as text_err:
                print("Scene text overlay failed:",
                      type(text_err).__name__, str(text_err)[:200])
        img_path = WORK / f"scene_{index:02d}.png"
        image.save(img_path, format="PNG")
        scene_image_paths.append(img_path)

    # Align total duration with the sum of scene durations (avoid audio drift)
    sum_scenes = sum(scene_durations)
    if abs(sum_scenes - total_seconds) > 0.05:
        print(
            f"Adjusting total_seconds from {total_seconds:.3f}s "
            f"to scene sum {sum_scenes:.3f}s"
        )
        total_seconds = sum_scenes

    print("\nScene timing:")
    t0 = 0.0
    for i, d in enumerate(scene_durations):
        print(f"  scene {i+1}: {t0:.2f}s → {t0+d:.2f}s ({d:.2f}s)")
        t0 += d
    print(f"  total: {total_seconds:.2f}s")
    if voice_path:
        print(f"  voice file: {voice_path}")

    # ----- HyperFrames assembly -----
    print("\nBuilding HyperFrames composition...")
    project_dir = write_hyperframes_project(
        work_dir=WORK,
        output_dir=OUTPUT,
        scene_images=scene_image_paths,
        scene_durations=scene_durations,
        voice_path=Path(voice_path) if voice_path else None,
        subtitle_events=sub_events,
        total_duration=total_seconds,
        topic=topic,
    )

    output_path = OUTPUT / "christian_reel.mp4"
    output_path.unlink(missing_ok=True)

    print("Rendering with HyperFrames CLI (cwd = project with index.html)...")
    render_with_hyperframes(project_dir, output_path)

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("Final HyperFrames video was not created correctly.")

    print()
    print("=" * 55)
    print("HYPERFRAMES VIDEO CREATED SUCCESSFULLY")
    print("Output:", output_path)
    print("Size:", output_path.stat().st_size, "bytes")
    print("=" * 55)


if __name__ == "__main__":
    main()
