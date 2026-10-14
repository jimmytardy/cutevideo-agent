from __future__ import annotations

from pydantic import BaseModel, Field


class YouTubeBrand(BaseModel):
    title: str
    description: str
    keywords: list[str] = Field(default_factory=list)
    handle_suggestion: str = ""


class TikTokBrand(BaseModel):
    display_name: str = ""
    bio: str = ""
    default_caption_style: str = ""


class InstagramBrand(BaseModel):
    page_name: str = ""
    bio: str = ""


class ChannelBrandKit(BaseModel):
    slug: str
    name: str
    theme_category: str
    niche_prompt: str
    content_angle: str
    youtube: YouTubeBrand
    tiktok: TikTokBrand
    instagram: InstagramBrand
    default_tags: list[str] = Field(default_factory=list)
    media_source_priority: list[str] | None = None
    sample_video_titles: list[str] = Field(default_factory=list)
