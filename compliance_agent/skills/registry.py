from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from compliance_agent.hermes.runtime_config import WorkflowCredentialSet
from compliance_agent.models.schemas import MaterialType

GENERAL_WORKFLOW_KIND = "general"
CONTRACT_WORKFLOW_KIND = "contract"

GENERAL_ENV_AUTH = "general_env"
CONTRACT_ENV_AUTH = "contract_env"
HANDBOOK_ENV_AUTH = "handbook_env"


@dataclass(frozen=True)
class MaterialSkillSpec:
    material_type: MaterialType
    skill_name: str
    api_route: str
    workflow_kind: str
    public_material_type: str
    external_material_type: str
    default_query: str
    auth_strategy: str
    static_api_key: str = ""

    def resolve_api_key(self, credentials: WorkflowCredentialSet | Any) -> str:
        if self.auth_strategy == CONTRACT_ENV_AUTH:
            return str(getattr(credentials, "contract_api_key", "") or "")
        if self.auth_strategy == GENERAL_ENV_AUTH:
            return str(getattr(credentials, "general_api_key", "") or "")
        if self.auth_strategy == HANDBOOK_ENV_AUTH:
            return str(getattr(credentials, "handbook_api_key", "") or "")
        return ""


MATERIAL_SKILL_SPECS: tuple[MaterialSkillSpec, ...] = (
    MaterialSkillSpec(
        material_type=MaterialType.CONTRACT,
        skill_name="contract-compliance-check",
        api_route="contract-review-2.0",
        workflow_kind=CONTRACT_WORKFLOW_KIND,
        public_material_type=MaterialType.CONTRACT.value,
        external_material_type=MaterialType.CONTRACT.value,
        default_query="请执行合同合规审查",
        auth_strategy=CONTRACT_ENV_AUTH,
    ),
    MaterialSkillSpec(
        material_type=MaterialType.CLAUSE_BOOK,
        skill_name="clausebook-compliance-check",
        api_route="general-compliance-workflow",
        workflow_kind=GENERAL_WORKFLOW_KIND,
        public_material_type=MaterialType.CLAUSE_BOOK.value,
        external_material_type=MaterialType.CLAUSE_BOOK.value,
        default_query="请执行条款书合规审查",
        auth_strategy=GENERAL_ENV_AUTH,
    ),
    MaterialSkillSpec(
        material_type=MaterialType.HANDBOOK,
        skill_name="product-handbook-compliance-check",
        api_route="general-compliance-workflow",
        workflow_kind=GENERAL_WORKFLOW_KIND,
        public_material_type=MaterialType.HANDBOOK.value,
        external_material_type=MaterialType.HANDBOOK.value,
        default_query="请执行产品说明书合规审查",
        auth_strategy=HANDBOOK_ENV_AUTH,
    ),
    MaterialSkillSpec(
        material_type=MaterialType.MARKETING,
        skill_name="marketing-material-compliance-check",
        api_route="general-compliance-workflow",
        workflow_kind=GENERAL_WORKFLOW_KIND,
        public_material_type=MaterialType.MARKETING.value,
        external_material_type=MaterialType.MARKETING.value,
        default_query="请执行营销物料合规审查",
        auth_strategy=GENERAL_ENV_AUTH,
    ),
    MaterialSkillSpec(
        material_type=MaterialType.POSTER,
        skill_name="poster-compliance-check",
        api_route="general-compliance-workflow",
        workflow_kind=GENERAL_WORKFLOW_KIND,
        public_material_type=MaterialType.POSTER.value,
        external_material_type=MaterialType.POSTER.value,
        default_query="请执行海报合规审查",
        auth_strategy=GENERAL_ENV_AUTH,
    ),
)

MATERIAL_SKILL_BY_TYPE: dict[MaterialType, MaterialSkillSpec] = {
    spec.material_type: spec for spec in MATERIAL_SKILL_SPECS
}
MATERIAL_SKILL_BY_NAME: dict[str, MaterialSkillSpec] = {
    spec.skill_name: spec for spec in MATERIAL_SKILL_SPECS
}
MATERIAL_TYPE_TO_SKILL: dict[MaterialType, str] = {
    spec.material_type: spec.skill_name for spec in MATERIAL_SKILL_SPECS
}
SKILL_SPECS: list[tuple[str, MaterialType]] = [
    (spec.skill_name, spec.material_type) for spec in MATERIAL_SKILL_SPECS
]
SUPPORTED_MATERIAL_TYPES = frozenset(MATERIAL_SKILL_BY_TYPE)
SUPPORTED_MATERIAL_TYPE_LABELS = tuple(spec.public_material_type for spec in MATERIAL_SKILL_SPECS)
SUPPORTED_MATERIAL_TYPE_OPTIONS = "/".join(SUPPORTED_MATERIAL_TYPE_LABELS)
AUTO_CLASSIFICATION_MATERIAL_TYPE_OPTIONS = f"{SUPPORTED_MATERIAL_TYPE_OPTIONS}/其它"


def get_material_skill_spec(material_type: MaterialType | None) -> MaterialSkillSpec | None:
    if material_type is None:
        return None
    return MATERIAL_SKILL_BY_TYPE.get(material_type)


def get_material_skill_spec_by_name(skill_name: str) -> MaterialSkillSpec | None:
    return MATERIAL_SKILL_BY_NAME.get(skill_name)


def default_query_for_material_type(material_type: MaterialType) -> str:
    spec = get_material_skill_spec(material_type)
    if spec is None:
        return "请执行合规审查"
    return spec.default_query
