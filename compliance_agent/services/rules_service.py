from __future__ import annotations

from compliance_agent.models.schemas import ComplianceRequest, MaterialType


def build_rules_context(req: ComplianceRequest) -> dict:
    context = {
        "material_type": req.material_type.value,
        "forbidden_words": ["国家级", "绝对收益", "保本保收益", "稳赚不赔"],
        "ambiguous_words": ["最高", "唯一", "最佳", "全面覆盖"],
        "citations": [],
    }

    if req.material_type == MaterialType.CONTRACT:
        context["citations"] = ["中华人民共和国民法典", "民事诉讼法", "仲裁法"]
        context["contract_type"] = req.contract_type or "通用"
        context["statement"] = req.statement or "甲方"
        context["scale"] = req.scale or "均势"
        if req.json_rules:
            context["json_rules_count"] = len(req.json_rules)

    elif req.material_type == MaterialType.CLAUSE_BOOK:
        context["citations"] = ["人身保险负面清单", "保险法司法解释三"]
    elif req.material_type == MaterialType.HANDBOOK:
        context["citations"] = ["消费者权益保护相关披露规范"]
    elif req.material_type == MaterialType.MARKETING:
        context["citations"] = ["广告法", "金融营销宣传规范"]

    return context
