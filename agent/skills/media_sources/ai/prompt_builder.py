from __future__ import annotations


def build_documentary_prompt(
    prompt: str,
    *,
    theme_category: str = "",
    editorial_tone: str = "",
    aspect_ratio: str = "16:9",
) -> str:
    orientation = "portrait 9:16 vertical" if aspect_ratio == "9:16" else "landscape 16:9 horizontal"
    tone = editorial_tone or "documentaire"
    category = theme_category or "éducatif"
    return (
        f"Documentary stock photo, {orientation}, natural lighting, high detail, photorealistic. "
        f"Theme: {category}. Tone: {tone}. Subject: {prompt}. "
        "No text, no watermark, no logo, no collage."
    )[:4000]
