"""Skills package — re-exports the discovery API from :mod:`skills.skills`."""

from backend.skills.skills import (
    LEGACY_SKILLS_DIR,
    PROJECT_SKILLS_DIR,
    SKILL_FILE_NAME,
    SKILL_NAME_PATTERN,
    SKILL_SOURCES,
    SkillMetadata,
    _parse_frontmatter,
    _read_skill,
    discover_skills,
    render_skills_prompt,
)

__all__ = [
    "LEGACY_SKILLS_DIR",
    "PROJECT_SKILLS_DIR",
    "SKILL_FILE_NAME",
    "SKILL_NAME_PATTERN",
    "SKILL_SOURCES",
    "SkillMetadata",
    "_parse_frontmatter",
    "_read_skill",
    "discover_skills",
    "render_skills_prompt",
]
