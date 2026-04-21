from hermes_cli.compliance_profile import (
    COMPLIANCE_PERSONALITY_PROMPT,
    COMPLIANCE_TOOLSET,
    DEFAULT_COMPLIANCE_EXTERNAL_SKILLS_DIR,
    merge_compliance_profile_defaults,
)


def test_merge_defaults_seeds_compliance_toolset_and_prompt():
    merged = merge_compliance_profile_defaults({})

    assert merged["platform_toolsets"]["cli"] == [COMPLIANCE_TOOLSET]
    assert merged["platform_toolsets"]["api_server"] == [COMPLIANCE_TOOLSET]
    assert merged["skills"]["preload"]["api_server"] == ["compliance-workflow-cn"]
    assert merged["agent"]["system_prompt"] == COMPLIANCE_PERSONALITY_PROMPT


def test_merge_defaults_replaces_plain_default_cli_toolset():
    skills_dir = "/tmp/compliance-skills"
    merged = merge_compliance_profile_defaults(
        {"platform_toolsets": {"cli": ["hermes-cli"]}},
        external_skills_dir=skills_dir,
    )

    assert merged["platform_toolsets"]["cli"] == [COMPLIANCE_TOOLSET]
    assert merged["platform_toolsets"]["api_server"] == [COMPLIANCE_TOOLSET]
    assert merged["skills"]["external_dirs"] == [skills_dir]
    assert merged["skills"]["preload"]["api_server"] == ["compliance-workflow-cn"]


def test_merge_defaults_preserves_custom_cli_toolsets_and_prompt():
    skills_dir = "/tmp/compliance-skills"
    merged = merge_compliance_profile_defaults(
        {
            "platform_toolsets": {"cli": ["web", "file"]},
            "agent": {"system_prompt": "custom"},
            "skills": {"external_dirs": [skills_dir]},
        },
        external_skills_dir=skills_dir,
    )

    assert merged["platform_toolsets"]["cli"] == ["web", "file"]
    assert merged["platform_toolsets"]["api_server"] == [COMPLIANCE_TOOLSET]
    assert merged["agent"]["system_prompt"] == "custom"
    assert merged["skills"]["external_dirs"] == [skills_dir]
    assert merged["skills"]["preload"]["api_server"] == ["compliance-workflow-cn"]
