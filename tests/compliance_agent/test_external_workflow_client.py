from compliance_agent.models.schemas import ComplianceRequest, MaterialType, UploadFile
from compliance_agent.services.external_workflow_client import (
    _collect_answer_from_stream,
    _extract_answer_from_payload,
    build_contract_payload,
    build_general_payload,
)


def test_contract_payload_preserves_image_input_type():
    req = ComplianceRequest(
        user="tester",
        material_type=MaterialType.CONTRACT,
        input_file=UploadFile(type="image", local_path="/tmp/material.png"),
    )

    payload = build_contract_payload(req, upload_file_id="file-123")

    assert payload["inputs"]["f"]["type"] == "image"
    assert payload["inputs"]["f"]["upload_file_id"] == "file-123"


def test_general_payload_preserves_image_input_type():
    req = ComplianceRequest(
        user="tester",
        material_type=MaterialType.POSTER,
        input_file=UploadFile(type="image", local_path="/tmp/poster.png"),
    )

    payload = build_general_payload(req, upload_file_id="file-456")

    assert payload["inputs"]["input_file"]["type"] == "image"
    assert payload["inputs"]["input_file"]["upload_file_id"] == "file-456"


def test_extract_answer_reads_workflow_finished_outputs():
    payload = {
        "event": "workflow_finished",
        "data": {"outputs": {"answer": "检测结果"}},
    }

    assert _extract_answer_from_payload(payload) == "检测结果"


def test_collect_answer_from_stream_reads_workflow_finished_outputs():
    raw = 'data: {"event":"workflow_finished","data":{"outputs":{"answer":"检测结果"}}}\n\n'

    assert _collect_answer_from_stream(raw) == "检测结果"
