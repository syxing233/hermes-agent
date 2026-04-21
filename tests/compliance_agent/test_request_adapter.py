import os
import unicodedata

import pytest
from pathlib import Path

from compliance_agent.hermes.request_adapter import adapt_review_request, coerce_file_paths


def test_adapt_review_request_uses_context_text_for_file_review(tmp_path):
    sample = tmp_path / "contract.docx"
    sample.write_text("hello", encoding="utf-8")

    adapted = adapt_review_request(
        file_paths=[str(sample)],
        text="补充说明",
        material_type="contract",
        user="tester",
    )

    assert len(adapted.sources) == 1
    assert adapted.sources[0].source_type == "file"
    assert adapted.sources[0].local_path == str(sample.resolve())
    assert adapted.material_type.value == "合同"
    assert adapted.context_text == "补充说明"
    assert adapted.user == "tester"


def test_adapt_review_request_can_treat_text_as_source(tmp_path):
    sample = tmp_path / "poster.png"
    sample.write_bytes(b"image")

    adapted = adapt_review_request(
        file_paths=[str(sample)],
        text="图片上的文案",
        text_as_source=True,
    )

    assert len(adapted.sources) == 2
    assert adapted.sources[0].source_type == "file"
    assert adapted.sources[1].source_type == "text"
    assert adapted.sources[1].input_text == "图片上的文案"
    assert adapted.context_text is None


def test_coerce_file_paths_returns_empty_for_none():
    assert coerce_file_paths(None) == []
    assert coerce_file_paths([]) == []


def test_coerce_file_paths_resolves_relative_path_with_cwd(tmp_path):
    sample = tmp_path / "contract.pdf"
    sample.write_text("content", encoding="utf-8")

    result = coerce_file_paths("contract.pdf", cwd=tmp_path)
    assert result == [sample.resolve()]


def test_coerce_file_paths_defaults_cwd_to_path_cwd(tmp_path, monkeypatch):
    sample = tmp_path / "doc.pdf"
    sample.write_text("content", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = coerce_file_paths("doc.pdf")
    assert result == [sample.resolve()]


def test_coerce_file_paths_expands_env_vars(tmp_path, monkeypatch):
    sample = tmp_path / "env_test.pdf"
    sample.write_text("content", encoding="utf-8")
    monkeypatch.setenv("TEST_FILE_DIR", str(tmp_path))

    result = coerce_file_paths("$TEST_FILE_DIR/env_test.pdf")
    assert result == [sample.resolve()]


def test_coerce_file_paths_expands_home(tmp_path, monkeypatch):
    sample = tmp_path / "homefile.txt"
    sample.write_text("x", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))

    result = coerce_file_paths("~/homefile.txt")
    assert result == [sample.resolve()]


def test_coerce_file_paths_strips_quotes(tmp_path):
    sample = tmp_path / "quoted.pdf"
    sample.write_text("q", encoding="utf-8")

    result = coerce_file_paths(f"'{sample}'", cwd=tmp_path)
    assert result == [sample.resolve()]

    result = coerce_file_paths(f'"{sample}"', cwd=tmp_path)
    assert result == [sample.resolve()]


def test_coerce_file_paths_raises_for_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="File not found"):
        coerce_file_paths(str(tmp_path / "nonexistent.pdf"))


def test_coerce_file_paths_raises_for_directory(tmp_path):
    subdir = tmp_path / "subdir"
    subdir.mkdir()

    with pytest.raises(ValueError, match="not a regular file"):
        coerce_file_paths(str(subdir))


def test_coerce_file_paths_raises_for_unreadable_file(tmp_path):
    sample = tmp_path / "secret.pdf"
    sample.write_text("s", encoding="utf-8")
    os.chmod(sample, 0o000)

    try:
        with pytest.raises(PermissionError, match="not readable"):
            coerce_file_paths(str(sample))
    finally:
        os.chmod(sample, 0o644)


def test_coerce_file_paths_handles_nfc_unicode(tmp_path):
    nfc_name = unicodedata.normalize("NFC", "合同文件.txt")
    sample = tmp_path / nfc_name
    sample.write_text("contract", encoding="utf-8")

    result = coerce_file_paths(str(sample), cwd=tmp_path)
    assert len(result) == 1
    assert result[0].exists()


def test_coerce_file_paths_single_string_input(tmp_path):
    sample = tmp_path / "one.pdf"
    sample.write_text("1", encoding="utf-8")

    result = coerce_file_paths(str(sample))
    assert len(result) == 1


def test_coerce_file_paths_list_input(tmp_path):
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    a.write_text("a", encoding="utf-8")
    b.write_text("b", encoding="utf-8")

    result = coerce_file_paths([str(a), str(b)])
    assert len(result) == 2