from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from compliance_agent.config import settings
from compliance_agent.hermes.runtime_config import WorkflowCredentialSet, WorkflowSettings
from compliance_agent.models.schemas import (
    ComplianceRequest,
    MaterialType,
    RuleItem,
    SkillCheckItem,
    SkillMeta,
    SkillRawOutput,
    SkillReviewReport,
    SkillSummary,
)
from compliance_agent.skills.registry import (
    CONTRACT_ENV_AUTH,
    CONTRACT_WORKFLOW_KIND,
    GENERAL_ENV_AUTH,
    GENERAL_WORKFLOW_KIND,
    HANDBOOK_ENV_AUTH,
    get_material_skill_spec,
)
from compliance_agent.services.external_workflow_client import ExternalWorkflowClient

_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".gif",
    ".webp",
    ".tiff",
    ".tif",
}

StreamItemCallback = Callable[[SkillMeta, SkillCheckItem], None]

_CONTRACT_BUILTIN_RULES = {
    "通用": [
        {
            "rule": "在合同引用法律条款中，确保引用法律文件名称的准确性和有效性",
            "level": "中",
            "content": "合同审查要点：核实法律文件有效性，更新失效引用（如旧法被民法典取代），确保全称准确，提供风险提示及修订建议。",
        },
        {
            "rule": "在合同标的条款中，审查标的的合法性、标的名称和数量的明确性和规范性，以及标的的特定性",
            "level": "高",
            "content": "审查合同标的合法性、名称、数量明确性及特定性，确保条款规范、完整。",
        },
        {
            "rule": "在合同违约责任条款中，根据双方的合同义务确定违约责任",
            "level": "高",
            "content": "审查违约责任条款的全面性、合理性与可执行性。",
        },
        {
            "rule": "在合同争议解决条款中，争议解决的约定是否完备、合理",
            "level": "中",
            "content": "审查诉讼/仲裁约定是否明确、有效。",
        },
        {
            "rule": "在合同形式与生效条款中，合同生效与签订日期审查",
            "level": "高",
            "content": "核实合同生效要件与签订日期。",
        },
    ],
    "委托合同": [
        {
            "rule": "是否有送达与通知条款",
            "level": "中",
            "content": "审查送达通知条款，需含：邮寄地址、收件人、手机号、邮箱、传真、微信号，签收即送达，诉讼有效。同意电子送达者，需明确标注。",
        },
        {
            "rule": "在合同形式与生效条款中，合同生效与签订日期审查",
            "level": "中",
            "content": "审查合同时，需确认生效日期明确，确保合同权利义务起始点，并核实签订日期准确无误，以防法律效力受损及潜在争议，缺失或错误则需及时修正。",
        },
        {
            "rule": "在合同委托要求条款中，受托人应当按照委托人的指令处理委托事务",
            "level": "高",
            "content": "受托人须遵循委托人指示处理事务，变动需委托人同意。紧急时可自行妥善处理，但须事后报告。这是《民法典》第九百二十二条的规定。",
        },
        {
            "rule": "在合同委托要求条款中，受托人应当向委托人报告事务办理进度、提交办理结果",
            "level": "高",
            "content": "《民法典》规定受托人需定期报告事务进展及结果，终止时提交最终结果，并转移处理所得财产给委托人。合同审查应聚焦于明确并确保委托要求的操作性和具体化。",
        },
        {
            "rule": "在合同履行地点条款中，明确合同的履行地点",
            "level": "高",
            "content": "审查合同时，需确认履行地点条款详尽准确，确保可执行性。",
        },
        {
            "rule": "在合同委托费用条款中，报酬计算方法、报酬支付方式、逾期支付报酬的后果",
            "level": "高",
            "content": "《民法典》928条：委托事务完成，按约付报酬；部分完成，报酬相应减。非受托人原因致事务未完或合同解，仍需付相应报酬，除非双方另有约定。",
        },
        {
            "rule": "在合同委托费用条款中，费用范围、费用负担、费用结算方式",
            "level": "中",
            "content": "委托合同应明确费用范围、结算方式，可约定垫付或预付及具体操作，包括预付金额、垫付利息计算等。未约定时，按《民法典》921条，委托人需偿还受托人垫付费用及利息。",
        },
        {
            "rule": "在合同税费条款中，合同中税款条款的审核",
            "level": "高",
            "content": "合同税款条款审核要点：明确价款含税与否及税率，核实总价计算，界定税费承担方，留意自然人收款的代扣税规定，确保合法性、明确性及可执行性，预防税务争议。",
        },
        {
            "rule": "发票条款的规范性与完整性审核",
            "level": "高",
            "content": "审查发票条款时，需核对开票时间、付款与发票次序，确认发票类型及纳税人资质，检查信息完整性与主体一致性，明确违规开票责任，确保条款合法、合规，有效防控风险。",
        },
        {
            "rule": "在合同委托人的赔偿责任条款中，约定委托人的赔偿责任",
            "level": "中",
            "content": "受托人在履行委托事务中，如遇非自身原因造成的损失，有权向委托人索赔。",
        },
        {
            "rule": "在合同受托人的赔偿责任条款中，约定受托人承担赔偿责任的条件及损失计算方式",
            "level": "中",
            "content": "有偿委托受损，受托人按实际损失赔偿；无偿委托过失致损，合理赔偿。超越权限造成损失，受托人须赔偿。",
        },
        {
            "rule": "在合同解除条款中，合同解除的条件以及解除后果",
            "level": "中",
            "content": "《民法典》允许委托合同双方基于信任缺失单方解除，要求提前通知并可能承担赔偿，确保稳定性与公平性。律师审查时关注解除通知期、财物交接、已完成事项处理及违约赔偿责任，遵循诚信原则。",
        },
        {
            "rule": "在合同任意解除权条款中，是否约定了任意解除权",
            "level": "高",
            "content": "《民法典》允许委托合同双方随时解除，需赔直接损失及可得利益。约定禁止解除可能无效，建议约定解约方按约定赔偿全部损失。",
        },
        {
            "rule": "保密条款及违约责任审查",
            "level": "中",
            "content": "委托合同中的保密条款至关重要，涉及委托事项及相关信息的保密，涵盖双方保密信息，属必要条款。",
        },
        {
            "rule": "在合同争议解决条款中，争议解决的约定是否完备、合理",
            "level": "中",
            "content": "合同审查要点：含争议解决条款，明确诉讼或仲裁方式；诉讼需定管辖法院，仲裁须指明仲裁机构；不动产争议管辖特殊考虑。确保条款明确，利于纠纷高效解决。",
        },
        {
            "rule": "在合同引用法律条款中，确保引用法律文件名称的准确性和有效性",
            "level": "中",
            "content": "合同审查要点：核实法律文件有效性，更新失效引用（如旧法被民法典取代），确保全称准确，提供风险提示及修订建议，依据权威法律资源验证，保障合同合法性及执行力。",
        },
        {
            "rule": "在合同委托事务条款中，委托事务是否明确、合法，委托期限是否明确",
            "level": "高",
            "content": "合同审查要点：委托事务须明确、合法，可为单一或多项，特指或概括委托，同时委托期限需清晰界定。",
        },
        {
            "rule": "在合同委托事项条款中，即委托人所委托的具体事务",
            "level": "高",
            "content": "委托合同审查要点：确保事务合法，不违法律公序良俗，非身份关系事项均可委托；明确委托事项与权限。",
        },
        {
            "rule": "在合同委托要求条款中，受托人应当亲自处理委托事务",
            "level": "高",
            "content": "《民法典》规定受托人原则上应亲自处理事务，转委托需委托人同意。紧急情况下，为委托人利益可未经同意转委托。合同审查时，应对转委托许可、程序及责任明确约定，预防争议。",
        },
    ],
}


def _missing_workflow_credential_message(spec: Any) -> str:
    if getattr(spec, "auth_strategy", "") == CONTRACT_ENV_AUTH:
        return "Missing compliance workflow credential: COMPLIANCE_CONTRACT_API_KEY"
    if getattr(spec, "auth_strategy", "") == HANDBOOK_ENV_AUTH:
        return "Missing compliance workflow credential: COMPLIANCE_HANDBOOK_API_KEY"
    if getattr(spec, "auth_strategy", "") == GENERAL_ENV_AUTH:
        return "Missing compliance workflow credential: COMPLIANCE_GENERAL_API_KEY"
    return "Missing compliance workflow credential"


class MaterialSkillRouter:
    def __init__(
        self,
        client: ExternalWorkflowClient | None = None,
        workflow_credentials: WorkflowCredentialSet | None = None,
        workflow_settings: WorkflowSettings | None = None,
    ):
        self.workflow_credentials = workflow_credentials or WorkflowCredentialSet(
            contract_api_key=getattr(settings, "contract_api_key", ""),
            general_api_key=getattr(settings, "general_api_key", ""),
            handbook_api_key=getattr(settings, "handbook_api_key", ""),
        )
        self.workflow_settings = workflow_settings or WorkflowSettings(
            base_url=getattr(settings, "workflow_base_url", ""),
            timeout_seconds=getattr(settings, "workflow_timeout_seconds", 30),
            max_retries=getattr(settings, "workflow_max_retries", 2),
        )
        self.client = client or ExternalWorkflowClient(
            base_url=self.workflow_settings.base_url,
            timeout_seconds=self.workflow_settings.timeout_seconds,
            max_retries=self.workflow_settings.max_retries,
        )

    def execute(self, req: ComplianceRequest, source: str = "", task_id: str | None = None) -> SkillReviewReport:
        resolved_task_id = task_id or f"task_{uuid4().hex[:10]}"
        spec = get_material_skill_spec(req.material_type)
        if spec is None:
            return self._unsupported(
                req=req,
                source=source,
                task_id=resolved_task_id,
                reason=f"当前物料类型暂不支持自动检测: {req.material_type.value}",
            )

        if spec.workflow_kind == CONTRACT_WORKFLOW_KIND:
            return self._run_contract(req=req, source=source, task_id=resolved_task_id)
        if spec.workflow_kind == GENERAL_WORKFLOW_KIND:
            return self._run_general(req=req, source=source, task_id=resolved_task_id)

        return self._unsupported(
            req=req,
            source=source,
            task_id=resolved_task_id,
            reason=f"当前物料类型暂不支持自动检测: {req.material_type.value}",
        )

    def execute_stream(
        self,
        req: ComplianceRequest,
        source: str = "",
        task_id: str | None = None,
        item_callback: StreamItemCallback | None = None,
    ) -> SkillReviewReport:
        resolved_task_id = task_id or f"task_{uuid4().hex[:10]}"
        spec = get_material_skill_spec(req.material_type)
        if spec is None:
            return self._unsupported(
                req=req,
                source=source,
                task_id=resolved_task_id,
                reason=f"当前物料类型暂不支持自动检测: {req.material_type.value}",
            )

        if spec.workflow_kind == CONTRACT_WORKFLOW_KIND:
            return self._run_contract_stream(
                req=req,
                source=source,
                task_id=resolved_task_id,
                item_callback=item_callback,
            )
        if spec.workflow_kind == GENERAL_WORKFLOW_KIND:
            return self._run_general_stream(
                req=req,
                source=source,
                task_id=resolved_task_id,
                item_callback=item_callback,
            )

        return self._unsupported(
            req=req,
            source=source,
            task_id=resolved_task_id,
            reason=f"当前物料类型暂不支持自动检测: {req.material_type.value}",
        )

    def _run_contract(self, req: ComplianceRequest, source: str, task_id: str) -> SkillReviewReport:
        spec = get_material_skill_spec(req.material_type)
        if spec is None:
            raise ValueError(f"Skill spec not found for material_type={req.material_type.value}")

        api_key = spec.resolve_api_key(self.workflow_credentials)
        if not api_key:
            raise ValueError(_missing_workflow_credential_message(spec))

        upload_file_id = self._resolve_upload_file_id(req=req, api_key=api_key)
        request_payload = self._contract_request_with_rules(req)
        meta = SkillMeta(
            skill_name=spec.skill_name,
            api_route=spec.api_route,
            input_file=self._meta_input_file(req),
            material_type=spec.public_material_type,
            query=request_payload.query,
            source=source,
            contract_type=request_payload.contract_type or "",
        )
        answer_markdown = self.client.run_contract_workflow(
            req=request_payload,
            upload_file_id=upload_file_id,
            api_key=api_key,
        )
        items = parse_contract_markdown(answer_markdown)

        return SkillReviewReport(
            task_id=task_id,
            meta=meta,
            summary=summarize_items(items),
            items=items,
            raw=SkillRawOutput(answer_markdown=answer_markdown),
            supported=True,
            needs_human_review=False,
            unsupported_reason="",
            status_trace=[],
        )

    def _run_contract_stream(
        self,
        req: ComplianceRequest,
        source: str,
        task_id: str,
        item_callback: StreamItemCallback | None = None,
    ) -> SkillReviewReport:
        spec = get_material_skill_spec(req.material_type)
        if spec is None:
            raise ValueError(f"Skill spec not found for material_type={req.material_type.value}")

        api_key = spec.resolve_api_key(self.workflow_credentials)
        if not api_key:
            raise ValueError(_missing_workflow_credential_message(spec))

        upload_file_id = self._resolve_upload_file_id(req=req, api_key=api_key)
        request_payload = self._contract_request_with_rules(req)
        meta = SkillMeta(
            skill_name=spec.skill_name,
            api_route=spec.api_route,
            input_file=self._meta_input_file(req),
            material_type=spec.public_material_type,
            query=request_payload.query,
            source=source,
            contract_type=request_payload.contract_type or "",
        )
        answer_markdown = self._collect_streamed_answer(
            chunks=self.client.stream_contract_workflow(
                req=request_payload,
                upload_file_id=upload_file_id,
                api_key=api_key,
            ),
            parse_block=parse_contract_block,
            item_callback=item_callback,
            meta=meta,
        )
        items = parse_contract_markdown(answer_markdown)

        return SkillReviewReport(
            task_id=task_id,
            meta=meta,
            summary=summarize_items(items),
            items=items,
            raw=SkillRawOutput(answer_markdown=answer_markdown),
            supported=True,
            needs_human_review=False,
            unsupported_reason="",
            status_trace=[],
        )

    def _run_general(self, req: ComplianceRequest, source: str, task_id: str) -> SkillReviewReport:
        spec = get_material_skill_spec(req.material_type)
        if spec is None:
            raise ValueError(f"Skill spec not found for material_type={req.material_type.value}")

        api_key = spec.resolve_api_key(self.workflow_credentials)
        if not api_key:
            raise ValueError(_missing_workflow_credential_message(spec))

        upload_file_id = self._resolve_upload_file_id(req=req, api_key=api_key)
        request_payload = self._general_request_with_input_type(req)
        meta = SkillMeta(
            skill_name=spec.skill_name,
            api_route=spec.api_route,
            input_file=self._meta_input_file(req),
            material_type=spec.public_material_type,
            query=req.query,
            source=source,
            contract_type="",
        )

        answer_markdown = self.client.run_general_workflow(
            req=request_payload,
            upload_file_id=upload_file_id,
            api_key=api_key,
        )
        items = parse_general_markdown(answer_markdown)
        raw_stat = extract_raw_stat(answer_markdown)

        return SkillReviewReport(
            task_id=task_id,
            meta=meta,
            summary=summarize_items(items, raw_stat=raw_stat),
            items=items,
            raw=SkillRawOutput(answer_markdown=answer_markdown),
            supported=True,
            needs_human_review=False,
            unsupported_reason="",
            status_trace=[],
        )

    def _run_general_stream(
        self,
        req: ComplianceRequest,
        source: str,
        task_id: str,
        item_callback: StreamItemCallback | None = None,
    ) -> SkillReviewReport:
        spec = get_material_skill_spec(req.material_type)
        if spec is None:
            raise ValueError(f"Skill spec not found for material_type={req.material_type.value}")

        api_key = spec.resolve_api_key(self.workflow_credentials)
        if not api_key:
            raise ValueError(_missing_workflow_credential_message(spec))

        upload_file_id = self._resolve_upload_file_id(req=req, api_key=api_key)
        request_payload = self._general_request_with_input_type(req)
        meta = SkillMeta(
            skill_name=spec.skill_name,
            api_route=spec.api_route,
            input_file=self._meta_input_file(req),
            material_type=spec.public_material_type,
            query=req.query,
            source=source,
            contract_type="",
        )
        answer_markdown = self._collect_streamed_answer(
            chunks=self.client.stream_general_workflow(
                req=request_payload,
                upload_file_id=upload_file_id,
                api_key=api_key,
            ),
            parse_block=parse_general_block,
            item_callback=item_callback,
            meta=meta,
        )
        items = parse_general_markdown(answer_markdown)
        raw_stat = extract_raw_stat(answer_markdown)

        return SkillReviewReport(
            task_id=task_id,
            meta=meta,
            summary=summarize_items(items, raw_stat=raw_stat),
            items=items,
            raw=SkillRawOutput(answer_markdown=answer_markdown),
            supported=True,
            needs_human_review=False,
            unsupported_reason="",
            status_trace=[],
        )

    def _unsupported(self, req: ComplianceRequest, source: str, task_id: str, reason: str) -> SkillReviewReport:
        return SkillReviewReport(
            task_id=task_id,
            meta=SkillMeta(
                skill_name="unsupported-material",
                api_route="none",
                input_file=self._meta_input_file(req),
                material_type=req.material_type.value,
                query=req.query,
                source=source,
                contract_type=req.contract_type or "",
            ),
            summary=SkillSummary(
                risk_count=0,
                no_risk_count=0,
                total_items=0,
                raw_stat=None,
            ),
            items=[],
            raw=SkillRawOutput(answer_markdown=""),
            supported=False,
            needs_human_review=True,
            unsupported_reason=reason,
            status_trace=[],
        )

    def _meta_input_file(self, req: ComplianceRequest) -> str:
        if req.input_file and req.input_file.local_path:
            return str(Path(req.input_file.local_path))
        return ""

    def _resolve_upload_file_id(self, req: ComplianceRequest, api_key: str) -> str:
        input_file = req.input_file
        if input_file and input_file.upload_file_id:
            return input_file.upload_file_id

        if input_file and input_file.local_path:
            return self.client.upload_file(path=Path(input_file.local_path), user=req.user, api_key=api_key)

        if req.input_text and req.input_text.strip():
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as tmp:
                tmp.write(req.input_text.strip())
                tmp_path = Path(tmp.name)
            try:
                return self.client.upload_file(path=tmp_path, user=req.user, api_key=api_key)
            finally:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

        raise ValueError("Missing input payload: provide upload_file_id, local_path, or input_text")

    def _contract_request_with_rules(self, req: ComplianceRequest) -> ComplianceRequest:
        if req.json_rules:
            return req

        contract_type = req.contract_type or "通用"
        fallback_rules = _CONTRACT_BUILTIN_RULES.get(contract_type) or _CONTRACT_BUILTIN_RULES["通用"]
        json_rules = [
            RuleItem(
                rule=item.get("rule", ""),
                level=item.get("level", "中"),
                content=item.get("content", ""),
            )
            for item in fallback_rules
        ]
        return req.model_copy(update={"json_rules": json_rules, "contract_type": contract_type})

    def _general_request_with_input_type(self, req: ComplianceRequest) -> ComplianceRequest:
        input_file = req.input_file
        if input_file is None:
            return req
        if input_file.type and input_file.type in {"document", "image"}:
            return req

        detected = "document"
        if input_file.local_path:
            ext = Path(input_file.local_path).suffix.lower()
            if ext in _IMAGE_EXTENSIONS:
                detected = "image"

        return req.model_copy(update={"input_file": input_file.model_copy(update={"type": detected})})

    def _collect_streamed_answer(
        self,
        *,
        chunks,
        parse_block: Callable[[str], list[SkillCheckItem]],
        item_callback: StreamItemCallback | None,
        meta: SkillMeta,
    ) -> str:
        answer_parts: list[str] = []
        pending = ""
        emitted_any = False

        for chunk in chunks:
            if not chunk:
                continue
            answer_parts.append(chunk)
            pending += chunk

            while "$term_end$" in pending:
                block, pending = pending.split("$term_end$", 1)
                for item in parse_block(block):
                    emitted_any = True
                    if item_callback is not None:
                        item_callback(meta, item)

        answer = "".join(answer_parts).strip()
        if not emitted_any and pending.strip():
            for item in parse_block(pending):
                if item_callback is not None:
                    item_callback(meta, item)
        return answer


def extract_section(text: str, section_names: list[str]) -> str:
    section_boundary = (
        r"检测项|检测内容|检测结果|检查结果|理由|对应原文内容|对应原文|检测依据|法规内容|修改建议|结果统计"
    )
    for name in section_names:
        inline_pattern = rf"(?mi)^\s*(?:#{{1,6}}\s*)?{re.escape(name)}\s*[:：]\s*(.+?)\s*$"
        inline_match = re.search(inline_pattern, text)
        if inline_match:
            value = inline_match.group(1).strip()
            if value:
                return value

        block_pattern = (
            rf"(?ms)^\s*(?:#{{1,6}}\s*)?{re.escape(name)}\s*[:：]?\s*$\n"
            rf"(.*?)(?=\n\s*(?:#{{1,6}}\s*(?:{section_boundary})\s*[:：]?|"
            rf"(?:{section_boundary})\s*[:：]|#{{1,6}}\s*\S)|\Z)"
        )
        match = re.search(block_pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def parse_general_markdown(answer_markdown: str) -> list[SkillCheckItem]:
    items: list[SkillCheckItem] = []
    chunks = _split_general_blocks(answer_markdown)
    for chunk in chunks:
        block = chunk.strip()
        if not block:
            continue
        result = extract_section(block, ["检测结果", "检查结果"]) or _infer_result_from_text(block)
        check_title = extract_section(block, ["检测内容"]) or _extract_block_title(block) or "检测项"
        if check_title.startswith("结果统计"):
            continue
        reason = extract_section(block, ["理由"])
        source_excerpt = extract_section(block, ["对应原文内容", "对应原文"])
        basis = extract_section(block, ["检测依据", "法规内容"])
        suggestion = extract_section(block, ["修改建议"])

        if not any([result, reason, source_excerpt, basis, suggestion]):
            continue

        items.append(
            SkillCheckItem(
                check_title=check_title,
                result=result,
                reason=reason,
                source_excerpt=source_excerpt,
                basis=basis,
                suggestion=suggestion,
            )
        )
    return items


def parse_general_block(block: str) -> list[SkillCheckItem]:
    text = (block or "").strip()
    if not text:
        return []
    return parse_general_markdown(text)


def parse_contract_markdown(answer_markdown: str) -> list[SkillCheckItem]:
    items: list[SkillCheckItem] = []
    for chunk in (answer_markdown or "").split("$term_end$"):
        block = chunk.strip()
        if not block or "检查结果" not in block:
            continue

        title_match = re.search(r"^#\s*(第.+?)\s*$", block, flags=re.M)
        if not title_match:
            title_match = re.search(r"^#\s*(.+?)\s*$", block, flags=re.M)
        check_title = title_match.group(1).strip() if title_match else "检测项"

        items.append(
            SkillCheckItem(
                check_title=check_title,
                result=extract_section(block, ["检查结果", "检测结果"]),
                reason=extract_section(block, ["理由"]),
                source_excerpt=extract_section(block, ["对应原文", "对应原文内容"]),
                basis=extract_section(block, ["法规内容", "检测依据"]),
                suggestion=extract_section(block, ["修改建议"]),
            )
        )
    return items


def parse_contract_block(block: str) -> list[SkillCheckItem]:
    text = (block or "").strip()
    if not text:
        return []
    return parse_contract_markdown(f"{text}\n$term_end$")


def extract_raw_stat(answer_markdown: str) -> Any:
    text = answer_markdown or ""
    patterns = [
        r"(?s)#{1,6}\s*结果统计\s*[:：]?\s*\n(?:```[a-zA-Z]*\n)?(\{[\s\S]*?\})\s*(?:```)?",
        r"(?s)(?:```[a-zA-Z]*\n)?(\{[\s\S]*?\"stat\"\s*:\s*\[[^\]]+\][\s\S]*?\})\s*(?:```)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        raw_json = match.group(1).strip()
        try:
            return json.loads(raw_json)
        except json.JSONDecodeError:
            return {"raw": raw_json}

    msg_match = re.search(r"共发现\s*(\d+)\s*个存在风险项\s*[，,]\s*(\d+)\s*个不存在风险项", text)
    if msg_match:
        risk = int(msg_match.group(1))
        no_risk = int(msg_match.group(2))
        return {
            "stat": [no_risk, risk],
            "msg": msg_match.group(0),
        }

    return None


def summarize_items(items: list[SkillCheckItem], raw_stat: Any | None = None) -> SkillSummary:
    risk_count = 0
    no_risk_count = 0

    if isinstance(raw_stat, dict):
        stats = raw_stat.get("stat")
        if isinstance(stats, list) and len(stats) >= 2:
            try:
                no_risk_count = int(stats[0])
                risk_count = int(stats[1])
                return SkillSummary(
                    risk_count=risk_count,
                    no_risk_count=no_risk_count,
                    total_items=risk_count + no_risk_count,
                    raw_stat=raw_stat,
                )
            except (TypeError, ValueError):
                pass

    for item in items:
        status = _classify_result(item.result)
        if status == "risk":
            risk_count += 1
        elif status == "no_risk":
            no_risk_count += 1

    return SkillSummary(
        risk_count=risk_count,
        no_risk_count=no_risk_count,
        total_items=len(items),
        raw_stat=raw_stat,
    )


def _classify_result(result: str) -> str:
    text = (result or "").strip()
    if not text:
        return "unknown"
    if "不存在风险" in text or "不提出风险" in text or "无风险" in text:
        return "no_risk"
    if "提出风险" in text or "存在风险" in text:
        return "risk"
    return "unknown"


def _split_general_blocks(answer_markdown: str) -> list[str]:
    text = (answer_markdown or "").strip()
    if not text:
        return []

    term_blocks = [block.strip() for block in text.split("$term_end$") if block.strip()]
    term_hits = [block for block in term_blocks if _looks_like_general_item(block)]
    if term_hits:
        return term_hits

    heading_blocks = re.split(r"(?m)^\s*#{1,6}\s*检测项\s*[:：]?\s*$", text)
    if len(heading_blocks) > 1:
        return [block.strip() for block in heading_blocks[1:] if block.strip()]

    content_blocks = re.split(r"(?m)^\s*(?:#{1,6}\s*)?检测内容\s*[:：]?\s*$", text)
    if len(content_blocks) > 1:
        normalized: list[str] = []
        for block in content_blocks[1:]:
            candidate = block.strip()
            if candidate:
                normalized.append(f"检测内容：\n{candidate}")
        if normalized:
            return normalized

    return [text]


def _looks_like_general_item(block: str) -> bool:
    text = block or ""
    return (
        "检测内容" in text
        or "检测结果" in text
        or "检查结果" in text
    )


def _infer_result_from_text(text: str) -> str:
    if "不存在风险" in text or "不提出风险" in text or "无风险" in text:
        return "不存在风险"
    if "提出风险" in text or "存在风险" in text:
        return "提出风险"
    return ""


def _extract_block_title(block: str) -> str:
    section_names = {
        "检测项",
        "检测内容",
        "检测结果",
        "检查结果",
        "理由",
        "对应原文内容",
        "对应原文",
        "检测依据",
        "法规内容",
        "修改建议",
        "结果统计",
    }

    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        heading_match = re.match(r"^#{1,6}\s*(.+?)\s*$", stripped)
        if not heading_match:
            continue

        title = heading_match.group(1).strip().strip(":：").strip("*").strip()
        if title and title not in section_names:
            return title

    return ""
