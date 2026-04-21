from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field


class MaterialType(str, Enum):
    CLAUSE_BOOK = "条款书"
    HANDBOOK = "产品说明书"
    CONTRACT = "合同"
    MARKETING = "营销物料"
    POSTER = "海报"
    OTHER = "其它"


_MATERIAL_TYPE_ALIASES: dict[str, MaterialType] = {
    "说明书": MaterialType.HANDBOOK,
    "产品说明书": MaterialType.HANDBOOK,
}


def normalize_material_type(value: Any) -> MaterialType | None:
    if value is None:
        return None
    if isinstance(value, MaterialType):
        return value

    text = str(value).strip()
    if not text:
        return None

    alias = _MATERIAL_TYPE_ALIASES.get(text)
    if alias is not None:
        return alias

    try:
        return MaterialType(text)
    except ValueError:
        return None


def _normalize_required_material_type(value: Any) -> Any:
    normalized = normalize_material_type(value)
    return normalized if normalized is not None else value


def _normalize_optional_material_type(value: Any) -> Any:
    if value is None:
        return None
    return _normalize_required_material_type(value)


NormalizedMaterialType = Annotated[MaterialType, BeforeValidator(_normalize_required_material_type)]
OptionalNormalizedMaterialType = Annotated[MaterialType | None, BeforeValidator(_normalize_optional_material_type)]


class RiskLevel(str, Enum):
    NONE = "无"
    LOW = "低"
    MEDIUM = "中"
    HIGH = "高"


class SkillName(str, Enum):
    # Legacy aliases, retained for fallback implementations only.
    CLAUSE = "clause_check"
    HANDBOOK = "handbook_check"
    CONTRACT = "contract_check"
    MARKETING = "marketing_quality_check"
    BASIC_RULE = "basic_rule_check"


class RuleItem(BaseModel):
    rule_id: str = Field(default="")
    rule: str
    level: RiskLevel = RiskLevel.MEDIUM
    content: str = ""


class UploadFile(BaseModel):
    type: str = Field(default="document", description="document or image")
    transfer_method: str = Field(default="local_file")
    upload_file_id: str | None = None
    local_path: str | None = None


class ComplianceRequest(BaseModel):
    user: str = "anonymous"
    query: str = ""
    material_type: NormalizedMaterialType = MaterialType.OTHER
    input_text: str | None = None
    input_file: UploadFile | None = None

    # Contract-specific controls
    contract_type: str | None = None
    statement: str | None = None
    scale: str | None = None
    json_rules: list[RuleItem] = Field(default_factory=list)

    # Optional manual review decision injected by caller
    human_review_override: bool | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class StatusEvent(BaseModel):
    at: datetime = Field(default_factory=datetime.utcnow)
    stage: str
    detail: str = ""
    operation: str = ""


class DocumentBlock(BaseModel):
    block_id: str
    page: int = 1
    text: str
    block_type: str = "paragraph"


class DocumentQuality(BaseModel):
    parse_source: str
    parser: str
    parse_confidence: float = 0.0
    ocr_confidence: float | None = None
    char_count: int = 0
    block_count: int = 0
    chunk_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    needs_review: bool = False


class Chunk(BaseModel):
    chunk_id: str
    text: str
    page: int
    start: int
    end: int
    chapter: str | None = None


class ExecutionPlan(BaseModel):
    labels: list[str] = Field(default_factory=list)
    selected_skills: list[str] = Field(default_factory=list)
    parallel: bool = True
    notes: str = ""


class DetectorSpec(BaseModel):
    detector_id: str
    material_type: str
    rule: str
    level: RiskLevel = RiskLevel.MEDIUM
    content: str = ""
    matchers: list[str] = Field(default_factory=list)
    endpoint_type: str = "general"


class Evidence(BaseModel):
    quote: str
    page: int = 1
    chunk_id: str | None = None


class Finding(BaseModel):
    finding_id: str
    source_skill: str
    check_item: str
    risk_level: RiskLevel
    has_risk: bool
    reason: str
    evidence: list[Evidence] = Field(default_factory=list)
    suggestion: str | None = None
    citation: str | None = None
    confidence: float = 0.6


class SkillResult(BaseModel):
    skill: str
    findings: list[Finding] = Field(default_factory=list)
    raw_output: str = ""
    elapsed_ms: int = 0


class ExternalCheckResult(BaseModel):
    check_item: str
    risk_level: RiskLevel = RiskLevel.MEDIUM
    has_risk: bool = True
    reason: str = ""
    evidence: str = "无"
    suggestion: str = "无"
    citation: str = ""
    raw_block: str = ""
    parse_warning: str | None = None


class AdjudicationResult(BaseModel):
    risk_score: float = 0.0
    max_risk_level: RiskLevel = RiskLevel.NONE
    total_findings: int = 0
    risk_findings: int = 0
    pass_findings: int = 0
    confidence: float = 1.0
    merged_findings: list[Finding] = Field(default_factory=list)


class HumanReview(BaseModel):
    required: bool = False
    reviewer: str | None = None
    comments: str | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)


class Suggestion(BaseModel):
    title: str
    detail: str
    priority: int = 2


class MaterialClassificationInfo(BaseModel):
    material_type: str = ""
    source: str = ""


class DetectReport(BaseModel):
    task_id: str
    material_type: NormalizedMaterialType
    material_classification: MaterialClassificationInfo | None = None
    summary: str
    risk_level: RiskLevel
    adjudication: AdjudicationResult
    suggestions: list[Suggestion] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    status_trace: list[StatusEvent] = Field(default_factory=list)


class SkillCheckItem(BaseModel):
    check_title: str = ""
    result: str = ""
    reason: str = ""
    source_excerpt: str = ""
    basis: str = ""
    suggestion: str = ""


class SkillSummary(BaseModel):
    risk_count: int = 0
    no_risk_count: int = 0
    total_items: int = 0
    raw_stat: Any | None = None


class SkillMeta(BaseModel):
    skill_name: str
    api_route: str
    input_file: str = ""
    material_type: str = ""
    query: str = ""
    source: str = ""
    contract_type: str = ""


class SkillRawOutput(BaseModel):
    answer_markdown: str = ""


class SkillReviewReport(BaseModel):
    task_id: str
    meta: SkillMeta
    material_classification: MaterialClassificationInfo | None = None
    summary: SkillSummary
    items: list[SkillCheckItem] = Field(default_factory=list)
    raw: SkillRawOutput = Field(default_factory=SkillRawOutput)
    supported: bool = True
    needs_human_review: bool = False
    unsupported_reason: str = ""
    status_trace: list[StatusEvent] = Field(default_factory=list)


class BatchSkillSummary(BaseModel):
    risk_count: int = 0
    no_risk_count: int = 0
    total_items: int = 0
    supported_count: int = 0
    unsupported_count: int = 0


class ReportAnalysis(BaseModel):
    summary_markdown: str = ""
    model: str = ""
    based_on_items: int = 0
    generated_by_model: bool = False


class BatchSkillReviewReport(BaseModel):
    task_id: str
    source_count: int = 0
    summary: BatchSkillSummary = Field(default_factory=BatchSkillSummary)
    reports: list[SkillReviewReport] = Field(default_factory=list)
    analysis: ReportAnalysis | None = None
    status_trace: list[StatusEvent] = Field(default_factory=list)


class ChatRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    role: ChatRole = ChatRole.USER
    content: str = ""


class AssistantMode(str, Enum):
    CHAT = "chat"
    DETECTION = "detection"


class AssistantIntentMeta(BaseModel):
    mode: AssistantMode = AssistantMode.CHAT
    reason: str = ""
    confidence: float = 0.0
    material_type: OptionalNormalizedMaterialType = None
    requested_material_type: OptionalNormalizedMaterialType = None


class AssistantRequest(BaseModel):
    user: str = "anonymous"
    message: str = ""
    input_text: str | None = None
    input_file: UploadFile | None = None
    material_type: OptionalNormalizedMaterialType = None
    conversation_id: str | None = None
    history: list[ChatMessage] = Field(default_factory=list)


class AssistantResponse(BaseModel):
    mode: AssistantMode
    reply: str
    intent: AssistantIntentMeta
    conversation_id: str | None = None
    report: BatchSkillReviewReport | None = None


class ConversationCreateRequest(BaseModel):
    user: str = "anonymous"
    title: str | None = None


class ConversationSummary(BaseModel):
    conversation_id: str
    user: str
    title: str = "新会话"
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime


class ConversationListResponse(BaseModel):
    conversations: list[ConversationSummary] = Field(default_factory=list)


class ConversationMessage(BaseModel):
    message_id: str
    conversation_id: str
    role: ChatRole
    content: str
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime


class ConversationMessagesResponse(BaseModel):
    conversation_id: str
    user: str
    messages: list[ConversationMessage] = Field(default_factory=list)
