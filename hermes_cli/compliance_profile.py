"""Compliance-first CLI profile helpers.

Keeps the compliance launcher/profile wiring in Python so defaults can be
unit-tested instead of being hidden in shell-only glue.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from hermes_cli.platforms import PLATFORMS

COMPLIANCE_PERSONALITY_NAME = "compliance-cn"
COMPLIANCE_PERSONALITY = {
    "description": "合规检测专用人格，优先走 Hermes 的合规检测工作流。",
    "system_prompt": (
        "你是一个合规检测专用助手。Hermes 是唯一对话外壳，内嵌 compliance engine 只负责检测事实生产。"
        "普通问答直接回答，不要默认转给独立 backend assistant。"
        "用户明确要求检查文件或文本合规时，优先调用 compliance_review。"
        "如果用户已经上传附件或给出可访问的本地文件路径，直接把该路径传给 compliance_review；"
        "不要先要求用户粘贴全文、转换 txt，或泛泛声称 PDF/路径存在兼容性问题。"
        "只有在兼容旧流程或用户明确要求时才使用 compliance_assistant，而且它不能创建独立会话或记忆。"
        "如果检测所需材料、路径或上下文不完整，先用 clarify 补齐关键信息。"
        "拿到结构化检测结果后，用中文给出结论、风险重点、依据/摘录和修改建议。"
    ),
}
COMPLIANCE_PERSONALITY_PROMPT = COMPLIANCE_PERSONALITY["system_prompt"]
COMPLIANCE_PRELOAD_SKILL = "compliance-workflow-cn"
COMPLIANCE_TOOLSET = "compliance-specialist"
DEFAULT_COMPLIANCE_EXTERNAL_SKILLS_DIR = ""


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        return []

    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _seed_platform_toolset(
    platform_toolsets: dict[str, Any],
    platform_key: str,
) -> None:
    """Replace the platform default with compliance when still unchanged."""
    current = _coerce_str_list(platform_toolsets.get(platform_key))
    default_toolset = PLATFORMS[platform_key].default_toolset
    if not current or current == [default_toolset]:
        platform_toolsets[platform_key] = [COMPLIANCE_TOOLSET]
    else:
        platform_toolsets[platform_key] = current


def _seed_platform_preload_skill(
    skills_cfg: dict[str, Any],
    platform_key: str,
    skill_name: str,
) -> None:
    """Ensure a platform-scoped preload skill is present exactly once."""
    preload_cfg = skills_cfg.get("preload")
    if not isinstance(preload_cfg, dict):
        preload_cfg = {}
        skills_cfg["preload"] = preload_cfg

    current = _coerce_str_list(preload_cfg.get(platform_key))
    if skill_name not in current:
        current.append(skill_name)
    preload_cfg[platform_key] = current


def merge_compliance_profile_defaults(
    config: dict[str, Any] | None,
    *,
    external_skills_dir: str | None = None,
) -> dict[str, Any]:
    """Return *config* with compliance-profile defaults applied.

    The compliance launcher uses a dedicated project-local HERMES_HOME
    profile, so it is safe to seed profile-specific defaults here without
    affecting anything outside this checkout.
    """
    merged = deepcopy(config or {})

    platform_toolsets = merged.setdefault("platform_toolsets", {})
    _seed_platform_toolset(platform_toolsets, "cli")
    _seed_platform_toolset(platform_toolsets, "api_server")

    skills_cfg = merged.setdefault("skills", {})
    external_dirs = _coerce_str_list(skills_cfg.get("external_dirs"))
    normalized_external_dir = str(external_skills_dir or "").strip()
    if normalized_external_dir and normalized_external_dir not in external_dirs:
        external_dirs.append(normalized_external_dir)
    if external_dirs:
        skills_cfg["external_dirs"] = external_dirs
    _seed_platform_preload_skill(
        skills_cfg,
        "api_server",
        COMPLIANCE_PRELOAD_SKILL,
    )

    agent_cfg = merged.setdefault("agent", {})
    if not str(agent_cfg.get("system_prompt") or "").strip():
        agent_cfg["system_prompt"] = COMPLIANCE_PERSONALITY_PROMPT

    display_cfg = merged.setdefault("display", {})
    current_personality = str(display_cfg.get("personality") or "").strip().lower()
    if not current_personality or current_personality == "kawaii":
        display_cfg["personality"] = COMPLIANCE_PERSONALITY_NAME

    return merged


def ensure_compliance_profile_config(
    *,
    external_skills_dir: str | None = None,
) -> dict[str, Any]:
    """Persist compliance-profile defaults into the active HERMES_HOME."""
    from hermes_cli.config import load_config, save_config

    current = load_config()
    merged = merge_compliance_profile_defaults(
        current,
        external_skills_dir=external_skills_dir,
    )
    if merged != current:
        save_config(merged)
    return merged
