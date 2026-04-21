from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from compliance_agent.models.schemas import Chunk, ComplianceRequest, DocumentBlock, DocumentQuality

_TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".csv",
    ".tsv",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
    ".htm",
    ".log",
}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}
_HEADING_RE = re.compile(r"^(第[一二三四五六七八九十百千万0-9]+[条章节款]|[0-9]+(\.[0-9]+)*\s|[（(][一二三四五六七八九十0-9]+[）)])")
_MAX_ZIP_FILES = 20
_MAX_ZIP_CHILD_CHARS = 8000


def parse_document_with_quality(req: ComplianceRequest) -> tuple[str, list[DocumentBlock], DocumentQuality]:
    text, parser, source, ocr_confidence, warnings = _extract_text_by_request(req)
    text = (text or "").strip()

    blocks = _to_blocks(text)
    parse_confidence = _estimate_parse_confidence(
        parser=parser,
        char_count=len(text),
        warning_count=len(warnings),
    )

    quality = DocumentQuality(
        parse_source=source,
        parser=parser,
        parse_confidence=parse_confidence,
        ocr_confidence=ocr_confidence,
        char_count=len(text),
        block_count=len(blocks),
        warnings=warnings,
    )
    return text, blocks, quality


def parse_document(req: ComplianceRequest) -> tuple[str, list[DocumentBlock]]:
    text, blocks, _ = parse_document_with_quality(req)
    return text, blocks


def blocks_from_text(text: str) -> list[DocumentBlock]:
    return _to_blocks((text or "").strip())


def build_chunks(blocks: list[DocumentBlock], chunk_size: int = 480, overlap: int = 80) -> list[Chunk]:
    if not blocks:
        return []

    chunk_size = max(120, chunk_size)
    overlap = max(0, min(overlap, chunk_size // 3))

    sections = _group_blocks_by_section(blocks)
    chunks: list[Chunk] = []

    for section_title, section_page, section_text in sections:
        if len(section_text) <= chunk_size:
            chunks.append(
                Chunk(
                    chunk_id=f"chunk_{len(chunks) + 1}",
                    text=section_text,
                    page=section_page,
                    start=0,
                    end=len(section_text),
                    chapter=section_title,
                )
            )
            continue

        for start, end in _window_slices(len(section_text), chunk_size, overlap):
            chunk_text = section_text[start:end].strip()
            if not chunk_text:
                continue
            chunks.append(
                Chunk(
                    chunk_id=f"chunk_{len(chunks) + 1}",
                    text=chunk_text,
                    page=section_page,
                    start=start,
                    end=end,
                    chapter=section_title,
                )
            )

    return chunks


def _to_blocks(text: str) -> list[DocumentBlock]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    blocks: list[DocumentBlock] = []
    page = 1
    for i, line in enumerate(lines, start=1):
        block_type = "heading" if _looks_like_heading(line) else "paragraph"
        blocks.append(
            DocumentBlock(
                block_id=f"blk_{i}",
                page=page,
                text=line,
                block_type=block_type,
            )
        )
        if i % 30 == 0:
            page += 1
    return blocks


def _group_blocks_by_section(blocks: list[DocumentBlock]) -> list[tuple[str, int, str]]:
    sections: list[tuple[str, int, str]] = []

    current_title = "未分节"
    current_page = blocks[0].page if blocks else 1
    current_lines: list[str] = []

    for block in blocks:
        text = block.text.strip()
        if not text:
            continue

        is_heading = block.block_type == "heading" or _looks_like_heading(text)
        if is_heading:
            if current_lines:
                sections.append((current_title, current_page, "\n".join(current_lines).strip()))
            current_title = text
            current_page = block.page
            current_lines = [text]
            continue

        if not current_lines:
            current_page = block.page
        current_lines.append(text)

    if current_lines:
        sections.append((current_title, current_page, "\n".join(current_lines).strip()))

    # Fallback: if all sections are empty for any reason.
    if not sections and blocks:
        joined = "\n".join(b.text for b in blocks if b.text.strip())
        if joined.strip():
            sections.append(("未分节", blocks[0].page, joined.strip()))

    return sections


def _window_slices(total: int, size: int, overlap: int) -> list[tuple[int, int]]:
    step = max(1, size - overlap)
    slices: list[tuple[int, int]] = []

    start = 0
    while start < total:
        end = min(total, start + size)
        slices.append((start, end))
        if end >= total:
            break
        start += step

    return slices


def _extract_text_by_request(
    req: ComplianceRequest,
) -> tuple[str, str, str, float | None, list[str]]:
    text = (req.input_text or "").strip()
    if text:
        return text, "inline_text", "input_text", None, []

    if not req.input_file:
        return "", "none", "none", None, ["未提供 input_text 或 input_file"]

    if req.input_file.local_path:
        return _extract_text_from_path(Path(req.input_file.local_path), allow_zip=True)

    if req.input_file.upload_file_id:
        return "", "upload_file_id_placeholder", "upload_file_id", None, [
            "仅提供 upload_file_id，本地文档理解层无法读取正文内容",
        ]

    return "", "none", "none", None, ["input_file 缺少 local_path/upload_file_id"]


def _extract_text_from_path(path: Path, allow_zip: bool) -> tuple[str, str, str, float | None, list[str]]:
    warnings: list[str] = []

    if not path.exists():
        return "", "none", "local_path", None, [f"文件不存在: {path}"]

    suffix = path.suffix.lower()

    if suffix in _TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8", errors="ignore"), "text_file", "local_path", None, warnings

    if suffix == ".docx":
        text, parser, parser_warnings = _extract_docx(path)
        return text, parser, "local_path", None, parser_warnings

    if suffix == ".doc":
        text, parser, parser_warnings = _extract_doc(path)
        return text, parser, "local_path", None, parser_warnings

    if suffix == ".pdf":
        text, parser, ocr_conf, parser_warnings = _extract_pdf(path)
        return text, parser, "local_path", ocr_conf, parser_warnings

    if suffix in _IMAGE_SUFFIXES:
        text, ocr_conf, parser_warnings = _extract_image(path)
        return text, "image_tesseract", "local_path", ocr_conf, parser_warnings

    if suffix in {".xlsx", ".xlsm"}:
        text, parser_warnings = _extract_xlsx(path)
        return text, "xlsx_xml", "local_path", None, parser_warnings

    if suffix == ".zip" and allow_zip:
        text, ocr_conf, parser_warnings = _extract_zip_bundle(path)
        return text, "zip_bundle", "local_path", ocr_conf, parser_warnings

    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        warnings.append(f"未知扩展名按文本读取: {suffix or 'none'}")
        return content, "binary_fallback", "local_path", None, warnings
    except Exception:
        return "", "none", "local_path", None, [f"不支持解析的文件类型: {suffix or path.name}"]


def _extract_doc(path: Path) -> tuple[str, str, list[str]]:
    failures: list[str] = []

    output, warning = _extract_with_textutil(path)
    if output and output.strip():
        return output, "doc_textutil", []
    if warning:
        failures.append(warning)

    output, warning = _extract_with_soffice(path)
    if output and output.strip():
        return output, "doc_soffice", []
    if warning:
        failures.append(warning)

    antiword = shutil_which("antiword")
    if antiword:
        try:
            output = subprocess.check_output(
                [antiword, str(path)],
                encoding="utf-8",
                errors="ignore",
                stderr=subprocess.DEVNULL,
            )
            if output.strip():
                return output, "doc_antiword", []
            failures.append("antiword 解析 .doc 结果为空")
        except Exception:
            failures.append("antiword 解析 .doc 失败")

    catdoc = shutil_which("catdoc")
    if catdoc:
        try:
            output = subprocess.check_output(
                [catdoc, "-d", "utf-8", str(path)],
                encoding="utf-8",
                errors="ignore",
                stderr=subprocess.DEVNULL,
            )
            if output.strip():
                return output, "doc_catdoc", []
            failures.append("catdoc 解析 .doc 结果为空")
        except Exception:
            failures.append("catdoc 解析 .doc 失败")

    if failures:
        return "", "none", failures
    return "", "none", ["当前环境缺少 .doc 解析器（textutil/soffice/antiword/catdoc）"]


def _extract_docx(path: Path) -> tuple[str, str, list[str]]:
    failures: list[str] = []

    output, warning = _extract_with_textutil(path)
    if output and output.strip():
        return output, "docx_textutil", []
    if warning:
        failures.append(warning)

    output, warning = _extract_with_soffice(path)
    if output and output.strip():
        return output, "docx_soffice", []
    if warning:
        failures.append(warning)

    text, warnings = _extract_docx_xml(path)
    if text.strip():
        return text, "docx_xml", []

    failures.extend(warnings)
    if failures:
        return "", "none", failures
    return "", "none", ["docx 解析失败"]


def _extract_with_textutil(path: Path) -> tuple[str | None, str | None]:
    textutil = shutil_which("textutil")
    if not textutil:
        return None, None

    try:
        output = subprocess.check_output(
            [textutil, "-convert", "txt", "-stdout", str(path)],
            encoding="utf-8",
            errors="ignore",
            stderr=subprocess.DEVNULL,
        )
        if output.strip():
            return output, None
        return "", "textutil 解析结果为空"
    except Exception:
        return None, "textutil 解析失败"


def _extract_with_soffice(path: Path) -> tuple[str | None, str | None]:
    office_cmd = shutil_which("soffice") or shutil_which("libreoffice")
    if not office_cmd:
        return None, None

    command_name = Path(office_cmd).name
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_dir = Path(tmp_dir)
        try:
            subprocess.check_call(
                [office_cmd, "--headless", "--convert-to", "txt:Text", "--outdir", str(out_dir), str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            return None, f"{command_name} 转换失败"

        candidates = sorted(p for p in out_dir.iterdir() if p.suffix.lower() == ".txt")
        if not candidates:
            return None, f"{command_name} 转换后未生成 txt 文件"

        preferred = out_dir / f"{path.stem}.txt"
        text_file = preferred if preferred.exists() else candidates[0]
        try:
            output = text_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None, f"{command_name} 输出文本读取失败"

        if output.strip():
            return output, None
        return "", f"{command_name} 解析结果为空"


def _extract_docx_xml(path: Path) -> tuple[str, list[str]]:
    warnings: list[str] = []
    texts: list[str] = []

    try:
        with zipfile.ZipFile(path) as zf:
            xml_bytes = zf.read("word/document.xml")
        root = ET.fromstring(xml_bytes)
        for node in root.findall(".//{*}t"):
            if node.text:
                texts.append(node.text)

        text = "\n".join(t.strip() for t in texts if t.strip())
        if not text:
            warnings.append("docx XML 解析成功但无可用文本")
        return text, warnings
    except Exception:
        return "", ["docx XML 解析失败"]


def _extract_pdf(path: Path) -> tuple[str, str, float | None, list[str]]:
    warnings: list[str] = []

    if importlib.util.find_spec("pypdf"):
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(str(path))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
            if text.strip():
                return text, "pdf_pypdf", None, warnings
            warnings.append("pypdf 解析完成但文本为空")
        except Exception:
            warnings.append("pypdf 解析失败")

    if shutil_which("pdftotext"):
        try:
            output = subprocess.check_output(
                ["pdftotext", "-layout", str(path), "-"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            if output.strip():
                return output, "pdf_pdftotext", None, warnings
            warnings.append("pdftotext 输出为空")
        except Exception:
            warnings.append("pdftotext 执行失败")

    if shutil_which("pdftoppm") and shutil_which("tesseract"):
        ocr_text, ocr_warnings = _extract_pdf_by_ocr(path)
        warnings.extend(ocr_warnings)
        if ocr_text.strip():
            return ocr_text, "pdf_ocr", 0.55, warnings

    if not warnings:
        warnings.append("当前环境缺少 PDF 可用解析器（pypdf/pdftotext/pdftoppm+tesseract）")
    return "", "none", None, warnings


def _extract_pdf_by_ocr(path: Path, max_pages: int = 5) -> tuple[str, list[str]]:
    warnings: list[str] = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        prefix = str(Path(tmp_dir) / "page")
        try:
            subprocess.check_call(
                ["pdftoppm", "-f", "1", "-l", str(max_pages), "-png", str(path), prefix],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            return "", ["pdftoppm 转图失败"]

        texts: list[str] = []
        images = sorted(Path(tmp_dir).glob("page-*.png"))
        for image in images:
            try:
                output = subprocess.check_output(
                    ["tesseract", str(image), "stdout", "-l", "chi_sim+eng"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                )
                if output.strip():
                    texts.append(output.strip())
            except Exception:
                warnings.append(f"OCR 失败: {image.name}")

        return "\n".join(texts), warnings


def _extract_image(path: Path) -> tuple[str, float | None, list[str]]:
    if not shutil_which("tesseract"):
        return "", None, ["系统缺少 tesseract，无法 OCR 图片"]

    try:
        output = subprocess.check_output(
            ["tesseract", str(path), "stdout", "-l", "chi_sim+eng"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        if not output.strip():
            return "", 0.45, ["tesseract 执行成功但文本为空"]
        return output, 0.6, []
    except Exception:
        return "", None, ["tesseract 执行失败"]


def _extract_xlsx(path: Path) -> tuple[str, list[str]]:
    warnings: list[str] = []
    lines: list[str] = []

    try:
        with zipfile.ZipFile(path) as zf:
            shared_strings = _read_shared_strings(zf)
            sheet_names = sorted(name for name in zf.namelist() if name.startswith("xl/worksheets/") and name.endswith(".xml"))

            for sheet_name in sheet_names:
                xml_bytes = zf.read(sheet_name)
                root = ET.fromstring(xml_bytes)
                sheet_title = Path(sheet_name).stem
                for row in root.findall(".//{*}row"):
                    cells: list[str] = []
                    for cell in row.findall("{*}c"):
                        ref = cell.attrib.get("r", "")
                        value = _xlsx_cell_text(cell, shared_strings)
                        if value:
                            cells.append(f"{ref}:{value}")
                    if cells:
                        lines.append(f"[{sheet_title}] " + " | ".join(cells))

        text = "\n".join(lines)
        if not text:
            warnings.append("xlsx 解析完成但无可用单元格文本")
        return text, warnings
    except Exception:
        return "", ["xlsx XML 解析失败"]


def _read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        xml_bytes = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []

    root = ET.fromstring(xml_bytes)
    result: list[str] = []
    for item in root.findall(".//{*}si"):
        tokens = [node.text for node in item.findall(".//{*}t") if node.text]
        result.append("".join(tokens).strip())
    return result


def _xlsx_cell_text(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")

    if cell_type == "inlineStr":
        text_nodes = cell.findall(".//{*}t")
        return "".join(node.text or "" for node in text_nodes).strip()

    value_node = cell.find("{*}v")
    if value_node is None or value_node.text is None:
        return ""

    raw = value_node.text.strip()
    if cell_type == "s":
        try:
            idx = int(raw)
            if 0 <= idx < len(shared_strings):
                return shared_strings[idx]
        except Exception:
            return ""
    return raw


def _extract_zip_bundle(path: Path) -> tuple[str, float | None, list[str]]:
    warnings: list[str] = []
    pieces: list[str] = []
    ocr_scores: list[float] = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        extract_root = Path(tmp_dir)

        try:
            with zipfile.ZipFile(path) as zf:
                files = [info for info in zf.infolist() if not info.is_dir()]
                if len(files) > _MAX_ZIP_FILES:
                    warnings.append(f"ZIP 文件过多，仅处理前{_MAX_ZIP_FILES}个")
                for info in files[:_MAX_ZIP_FILES]:
                    safe_rel = _safe_zip_relpath(info.filename)
                    if safe_rel is None:
                        warnings.append(f"跳过不安全路径: {info.filename}")
                        continue

                    out_path = extract_root / safe_rel
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, out_path.open("wb") as dst:
                        dst.write(src.read())

                    child_text, child_parser, _, child_ocr, child_warnings = _extract_text_from_path(
                        out_path,
                        allow_zip=False,
                    )
                    warnings.extend(f"{safe_rel}: {w}" for w in child_warnings)
                    if child_ocr is not None:
                        ocr_scores.append(child_ocr)

                    if child_text.strip():
                        snippet = child_text.strip()[:_MAX_ZIP_CHILD_CHARS]
                        pieces.append(f"[{safe_rel}] ({child_parser})\n{snippet}")
        except Exception:
            return "", None, ["zip 解包或解析失败"]

    if not pieces:
        warnings.append("zip 内未提取到可用文本")

    ocr_confidence = round(sum(ocr_scores) / len(ocr_scores), 3) if ocr_scores else None
    return "\n\n".join(pieces), ocr_confidence, warnings


def _safe_zip_relpath(name: str) -> Path | None:
    candidate = Path(name)
    parts = [part for part in candidate.parts if part not in {"", ".", ".."}]
    if not parts:
        return None
    if any(part.startswith("/") for part in parts):
        return None
    return Path(*parts)


def _estimate_parse_confidence(parser: str, char_count: int, warning_count: int) -> float:
    base = {
        "inline_text": 1.0,
        "text_file": 0.97,
        "docx_textutil": 0.9,
        "docx_soffice": 0.88,
        "docx_xml": 0.82,
        "doc_textutil": 0.8,
        "doc_soffice": 0.78,
        "doc_antiword": 0.72,
        "doc_catdoc": 0.72,
        "pdf_pypdf": 0.85,
        "pdf_pdftotext": 0.8,
        "pdf_ocr": 0.62,
        "image_tesseract": 0.6,
        "xlsx_xml": 0.75,
        "zip_bundle": 0.72,
        "binary_fallback": 0.45,
        "upload_file_id_placeholder": 0.25,
        "none": 0.0,
    }.get(parser, 0.4)

    if char_count == 0:
        base -= 0.4
    elif char_count < 50:
        base -= 0.25
    elif char_count < 200:
        base -= 0.12

    base -= min(0.3, warning_count * 0.08)
    return round(max(0.0, min(1.0, base)), 3)


def _looks_like_heading(line: str) -> bool:
    return bool(_HEADING_RE.match(line.strip()))


def shutil_which(command: str) -> str | None:
    for p in os.getenv("PATH", "").split(os.pathsep):
        candidate = Path(p) / command
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None
