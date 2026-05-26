from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import shutil
import sys
import zipfile
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from typing import Callable

import fitz
import streamlit as st


APP_TITLE = "Resolution Law Tools"
FOOTER_TOP_RATIO = 0.92
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class ToolDefinition:
    tool_id: str
    name: str
    category: str
    description: str
    render: Callable[[], None]


@dataclass
class ChunkRow:
    row_id: str
    source_file: str
    pages: str
    start_page: int
    end_page: int
    detected_beam: str
    filename_stem: str
    method: str
    issue: str
    include: bool


@dataclass
class SplitResult:
    source_file: str
    pages: str
    output_file: str
    beam_number: str
    method: str
    status: str


def inject_css() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background:
                linear-gradient(180deg, #f8fafc 0%, #eef4ff 44%, #f8fafc 100%);
            color: #0f172a;
        }
        [data-testid="stHeader"] {
            background: rgba(248, 250, 252, 0.88);
        }
        [data-testid="stSidebar"] {
            background: #0f172a;
        }
        [data-testid="stSidebar"] * {
            color: #e5e7eb;
        }
        [data-testid="stSidebar"] div[role="radiogroup"] label {
            border-radius: 12px;
            padding: 0.25rem 0.35rem;
        }
        .hub-hero {
            background: #ffffff;
            color: #0f172a;
            padding: 2rem 2.15rem;
            border: 1px solid #dbe4f0;
            border-radius: 20px;
            margin-bottom: 1.25rem;
            box-shadow: 0 18px 45px rgba(15, 23, 42, 0.08);
            position: relative;
            overflow: hidden;
        }
        .hub-hero:before {
            content: "";
            position: absolute;
            inset: 0 0 auto 0;
            height: 5px;
            background: linear-gradient(90deg, #2563eb, #14b8a6, #facc15);
        }
        .hub-hero h1 {
            margin: 0;
            font-size: 2.35rem;
            line-height: 1.05;
            letter-spacing: 0;
            color: #0f172a;
        }
        .hub-hero p {
            margin: 0.75rem 0 0;
            color: #475569;
            font-size: 1.03rem;
            max-width: 760px;
        }
        .tool-card {
            background: white;
            border: 1px solid #e2e8f0;
            border-radius: 16px;
            padding: 1.15rem 1.2rem;
            box-shadow: 0 10px 28px rgba(15, 23, 42, 0.05);
            min-height: 134px;
            transition: border-color 140ms ease, box-shadow 140ms ease, transform 140ms ease;
        }
        .tool-card.clickable {
            min-height: 160px;
        }
        .tool-card.clickable:hover {
            border-color: #93c5fd;
            box-shadow: 0 18px 40px rgba(37, 99, 235, 0.12);
            transform: translateY(-1px);
        }
        .tool-card h3 {
            margin: 0 0 0.35rem;
            color: #0f172a;
        }
        .tool-card p,
        .small-muted {
            color: #667085;
            font-size: 0.92rem;
        }
        .metric-strip {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.75rem;
            margin: 1rem 0;
        }
        .metric-box {
            background: white;
            border: 1px solid #e2e8f0;
            border-radius: 14px;
            padding: 0.85rem 1rem;
            box-shadow: 0 6px 18px rgba(15, 23, 42, 0.04);
        }
        .metric-box strong {
            display: block;
            color: #0f172a;
            font-size: 1.45rem;
        }
        .metric-box span {
            color: #667085;
            font-size: 0.88rem;
        }
        div[data-testid="stDownloadButton"] button,
        div[data-testid="stButton"] button {
            border-radius: 12px;
            font-weight: 650;
            border: 1px solid #cbd5e1;
            box-shadow: 0 5px 14px rgba(15, 23, 42, 0.06);
        }
        .section-label {
            color: #0f172a;
            font-size: 1.1rem;
            font-weight: 700;
            margin: 1rem 0 0.25rem;
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 0.5rem;
        }
        .stTabs [data-baseweb="tab"] {
            border-radius: 999px;
            background: #ffffff;
            border: 1px solid #e2e8f0;
            padding: 0.45rem 0.85rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def find_tesseract_executable() -> Path | None:
    env_value = os.environ.get("TESSERACT_CMD")
    if env_value and Path(env_value).exists():
        return Path(env_value)

    path_value = shutil.which("tesseract")
    if path_value:
        return Path(path_value)

    if sys.platform.startswith("win"):
        candidates = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tesseract-OCR" / "tesseract.exe",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Tesseract-OCR" / "tesseract.exe",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate

    return None


def dependency_status() -> dict[str, bool]:
    return {
        "PyMuPDF": importlib.util.find_spec("fitz") is not None,
        "Pillow": importlib.util.find_spec("PIL") is not None,
        "pytesseract": importlib.util.find_spec("pytesseract") is not None,
        "Tesseract OCR": find_tesseract_executable() is not None,
    }


def ocr_available() -> bool:
    return (
        importlib.util.find_spec("pytesseract") is not None
        and importlib.util.find_spec("PIL") is not None
        and find_tesseract_executable() is not None
    )


def configure_tesseract(pytesseract_module) -> None:
    executable = find_tesseract_executable()
    if executable is not None:
        pytesseract_module.pytesseract.tesseract_cmd = str(executable)


def sanitize_filename_stem(value: str, fallback: str) -> str:
    stem = value.strip()
    if stem.lower().endswith(".pdf"):
        stem = stem[:-4]
    stem = INVALID_FILENAME_CHARS.sub("_", stem)
    stem = re.sub(r"\s+", "_", stem).strip(" ._")
    return stem or fallback


def make_unique_stem(existing: set[str], requested_stem: str, fallback: str) -> str:
    base = sanitize_filename_stem(requested_stem, fallback)
    candidate = base
    counter = 2
    while candidate.lower() in existing:
        candidate = f"{base}_{counter:02d}"
        counter += 1
    existing.add(candidate.lower())
    return candidate


def number_tokens(text: str) -> list[str]:
    if not text:
        return []

    normalized = text.replace(",", "")
    tokens = re.findall(r"\b\d{2,}\b", normalized)
    if tokens:
        return tokens

    digits_only = re.sub(r"\D", "", normalized)
    if len(digits_only) >= 2:
        return [digits_only]

    return []


def find_beam_number_in_text(text: str) -> str | None:
    tokens = number_tokens(text)
    return tokens[-1] if tokens else None


def find_native_footer_number(page) -> str | None:
    page_rect = page.rect
    footer_y = page_rect.height * 0.74
    candidates: list[tuple[float, float, str]] = []

    for word in page.get_text("words"):
        x0, y0, x1, y1, text = word[:5]
        if y0 < footer_y:
            continue
        for token in number_tokens(text):
            candidates.append((float(y1), float(x0), token))

    if not candidates:
        text = page.get_text("text", clip=fitz.Rect(0, footer_y, page_rect.width, page_rect.height)) or ""
        return find_beam_number_in_text(text)

    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[-1][2]


def find_ocr_footer_number(page, ocr_error_callback: Callable[[Exception], None] | None = None) -> tuple[str | None, str]:
    try:
        from PIL import Image, ImageOps
        import pytesseract

        configure_tesseract(pytesseract)
        page_rect = page.rect
        footer_rect = fitz.Rect(0, page_rect.height * 0.74, page_rect.width, page_rect.height)
        matrix = fitz.Matrix(3, 3)
        pixmap = page.get_pixmap(matrix=matrix, clip=footer_rect, alpha=False)
        image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
        image = ImageOps.autocontrast(ImageOps.grayscale(image))

        data = pytesseract.image_to_data(
            image,
            config="--psm 6 -c tessedit_char_whitelist=0123456789",
            output_type=pytesseract.Output.DICT,
        )

        candidates: list[tuple[float, float, str]] = []
        for index, text in enumerate(data.get("text", [])):
            for token in number_tokens(text):
                top = float(data["top"][index])
                height = float(data["height"][index])
                left = float(data["left"][index])
                candidates.append((top + height, left, token))

        if candidates:
            candidates.sort(key=lambda item: (item[0], item[1]))
            return candidates[-1][2], "OCR"

        ocr_text = pytesseract.image_to_string(
            image,
            config="--psm 6 -c tessedit_char_whitelist=0123456789",
        )
        beam = find_beam_number_in_text(ocr_text)
        if beam:
            return beam, "OCR"
    except Exception as exc:
        if ocr_error_callback is not None:
            ocr_error_callback(exc)

    return None, "not found"


def extract_beam_number_from_page(
    page,
    use_ocr: bool,
    ocr_error_callback: Callable[[Exception], None] | None = None,
) -> tuple[str | None, str]:
    beam = find_native_footer_number(page)
    if beam:
        return beam, "native text"

    if not use_ocr:
        return None, "not found"

    return find_ocr_footer_number(page, ocr_error_callback)


def save_page_range_to_bytes(doc, start_page: int, end_page: int) -> bytes:
    out_doc = fitz.open()
    try:
        out_doc.insert_pdf(doc, from_page=start_page, to_page=end_page)
        buffer = BytesIO()
        out_doc.save(buffer, garbage=4, deflate=True)
        return buffer.getvalue()
    finally:
        out_doc.close()


def file_hash(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:12]


def uploaded_files_signature(uploaded_files) -> str:
    parts: list[str] = []
    for uploaded_file in uploaded_files:
        data = uploaded_file.getvalue()
        parts.append(f"{uploaded_file.name}:{len(data)}:{file_hash(data)}")
    return "|".join(sorted(parts))


def analyze_uploads(uploaded_files, odd_page_mode: str, missing_beam_mode: str) -> tuple[list[dict], list[str], dict[str, bytes]]:
    rows: list[ChunkRow] = []
    logs: list[str] = []
    file_bytes: dict[str, bytes] = {}
    fallback_counter = 1
    use_ocr = ocr_available()
    ocr_warning_logged = False

    if not use_ocr:
        logs.append("OCR is unavailable. Native PDFs can still be processed, but scanned PDFs need Tesseract OCR on the server.")

    def warn_ocr_once(exc: Exception) -> None:
        nonlocal ocr_warning_logged
        if not ocr_warning_logged:
            logs.append(f"OCR warning: {exc}")
            ocr_warning_logged = True

    for uploaded_file in uploaded_files:
        data = uploaded_file.getvalue()
        source_name = Path(uploaded_file.name).name
        source_id = f"{file_hash(data)}_{source_name}"
        file_bytes[source_id] = data

        try:
            doc = fitz.open(stream=data, filetype="pdf")
        except Exception as exc:
            logs.append(f"{source_name}: could not open PDF ({exc}).")
            continue

        try:
            page_count = doc.page_count
            logs.append(f"{source_name}: opened {page_count} page(s).")
            paired_page_count = page_count - (page_count % 2)

            for start_page in range(0, paired_page_count, 2):
                beam_number, method = extract_beam_number_from_page(doc[start_page + 1], use_ocr, warn_ocr_once)
                issue = ""
                include = True
                filename_stem = beam_number or ""

                if not beam_number:
                    if missing_beam_mode == "Skip missing beam pairs":
                        include = False
                        issue = "No beam number found; skipped by rule."
                    elif missing_beam_mode == "Use fallback names":
                        filename_stem = f"unnamed_{fallback_counter:03d}"
                        fallback_counter += 1
                        issue = "No beam number found; fallback name assigned."
                    else:
                        issue = "No beam number found; enter filename or uncheck include."

                rows.append(
                    ChunkRow(
                        row_id=f"{source_id}:{start_page}:{start_page + 1}",
                        source_file=source_name,
                        pages=f"{start_page + 1}-{start_page + 2}",
                        start_page=start_page,
                        end_page=start_page + 1,
                        detected_beam=beam_number or "",
                        filename_stem=filename_stem,
                        method=method,
                        issue=issue,
                        include=include,
                    )
                )

            if page_count % 2:
                orphan_page = page_count - 1
                if odd_page_mode == "Skip odd final pages":
                    filename_stem = ""
                    issue = "Odd final page; skipped by rule."
                    include = False
                elif odd_page_mode == "Review odd final pages":
                    filename_stem = ""
                    issue = "Odd final page; enter filename or uncheck include."
                    include = True
                else:
                    filename_stem = f"{Path(source_name).stem}_page_{page_count:03d}"
                    issue = "Odd final page saved as single-page output."
                    include = True

                rows.append(
                    ChunkRow(
                        row_id=f"{source_id}:{orphan_page}:{orphan_page}",
                        source_file=source_name,
                        pages=str(page_count),
                        start_page=orphan_page,
                        end_page=orphan_page,
                        detected_beam="",
                        filename_stem=filename_stem,
                        method="odd page",
                        issue=issue,
                        include=include,
                    )
                )
        finally:
            doc.close()

    return [asdict(row) for row in rows], logs, file_bytes


def build_zip(rows: list[dict], file_bytes: dict[str, bytes]) -> tuple[bytes | None, list[str]]:
    errors: list[str] = []
    output = BytesIO()
    used_names: set[str] = set()
    written = 0

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for row in rows:
            if not row.get("include"):
                continue

            filename_stem = str(row.get("filename_stem") or "").strip()
            if not filename_stem:
                errors.append(f"{row['source_file']} pages {row['pages']}: filename is blank.")
                continue

            source_key = str(row["row_id"]).split(":", 1)[0]
            data = file_bytes.get(source_key)
            if data is None:
                errors.append(f"{row['source_file']} pages {row['pages']}: source file data was not found.")
                continue

            try:
                doc = fitz.open(stream=data, filetype="pdf")
                try:
                    pdf_bytes = save_page_range_to_bytes(doc, int(row["start_page"]), int(row["end_page"]))
                finally:
                    doc.close()
            except Exception as exc:
                errors.append(f"{row['source_file']} pages {row['pages']}: could not split PDF ({exc}).")
                continue

            unique_stem = make_unique_stem(used_names, filename_stem, f"unnamed_{written + 1:03d}")
            archive.writestr(f"beam_split_results/{unique_stem}.pdf", pdf_bytes)
            written += 1

    if errors:
        return None, errors
    if written == 0:
        return None, ["No output files were selected. Check at least one row to include."]

    return output.getvalue(), []


def split_and_rename_pdfs(uploaded_files, include_odd_final_page: bool, use_fallback_names: bool) -> tuple[bytes | None, list[dict], list[str]]:
    logs: list[str] = []
    rows: list[SplitResult] = []
    output = BytesIO()
    used_names: set[str] = set()
    fallback_counter = 1
    written = 0
    use_ocr = ocr_available()
    ocr_warning_logged = False

    if not use_ocr:
        logs.append("OCR is unavailable on the server. Native PDFs may still work, but scanned PDFs need Tesseract OCR.")

    def warn_ocr_once(exc: Exception) -> None:
        nonlocal ocr_warning_logged
        if not ocr_warning_logged:
            logs.append(f"OCR warning: {exc}")
            ocr_warning_logged = True

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for uploaded_file in uploaded_files:
            data = uploaded_file.getvalue()
            source_name = Path(uploaded_file.name).name

            try:
                doc = fitz.open(stream=data, filetype="pdf")
            except Exception as exc:
                logs.append(f"{source_name}: could not open PDF ({exc}).")
                continue

            try:
                page_count = doc.page_count
                pair_page_count = page_count - (page_count % 2)

                for start_page in range(0, pair_page_count, 2):
                    end_page = start_page + 1
                    pages = f"{start_page + 1}-{end_page + 1}"
                    beam_number, method = extract_beam_number_from_page(doc[end_page], use_ocr, warn_ocr_once)
                    status = "Beam number found."

                    if beam_number:
                        stem = beam_number
                    elif use_fallback_names:
                        stem = f"unnamed_{fallback_counter:03d}"
                        fallback_counter += 1
                        status = "Beam number not found; fallback name used."
                    else:
                        logs.append(f"{source_name} pages {pages}: beam number not found; skipped.")
                        rows.append(
                            SplitResult(
                                source_file=source_name,
                                pages=pages,
                                output_file="",
                                beam_number="",
                                method="not found",
                                status="Skipped - beam number not found.",
                            )
                        )
                        continue

                    unique_stem = make_unique_stem(used_names, stem, f"unnamed_{fallback_counter:03d}")
                    output_file = f"{unique_stem}.pdf"
                    pdf_bytes = save_page_range_to_bytes(doc, start_page, end_page)
                    archive.writestr(output_file, pdf_bytes)
                    written += 1
                    rows.append(
                        SplitResult(
                            source_file=source_name,
                            pages=pages,
                            output_file=output_file,
                            beam_number=beam_number or "",
                            method=method,
                            status=status,
                        )
                    )

                if page_count % 2:
                    last_page = page_count - 1
                    if include_odd_final_page:
                        stem = f"{Path(source_name).stem}_page_{page_count:03d}"
                        unique_stem = make_unique_stem(used_names, stem, stem)
                        output_file = f"{unique_stem}.pdf"
                        pdf_bytes = save_page_range_to_bytes(doc, last_page, last_page)
                        archive.writestr(output_file, pdf_bytes)
                        written += 1
                        rows.append(
                            SplitResult(
                                source_file=source_name,
                                pages=str(page_count),
                                output_file=output_file,
                                beam_number="",
                                method="odd final page",
                                status="Included as single-page output.",
                            )
                        )
                    else:
                        logs.append(f"{source_name} page {page_count}: odd final page skipped.")
            finally:
                doc.close()

    if written == 0:
        return None, [asdict(row) for row in rows], logs + ["No PDF chunks were created."]

    return output.getvalue(), [asdict(row) for row in rows], logs


# ============================================================================
# Case Folder Comparison Tool — added to Resolution Law Tools
# Compares two folders of case-action-summary CSVs and produces an Excel
# report (New / Modified Summary / Modified Details / No Longer In File).
# Files are matched by case number (SM-YYYY-NNNNNN style), not by filename,
# so renames like 10080_68-... → 10080_01-... still pair correctly.
# Formatting-only differences (date padding, time padding, $ spacing,
# parens-vs-minus, CSV quoting) are normalized out before comparison.
# ============================================================================
import csv as _csv
import io as _io
import re as _re
from collections import defaultdict as _defaultdict

import openpyxl as _openpyxl
from openpyxl.styles import Font as _Font, PatternFill as _PatternFill, Alignment as _Alignment

_CASE_RE  = _re.compile(r"((?:SM|CV|DV|CC|JU|TR|TP)-\d{4}-\d{4,7})", _re.IGNORECASE)
_DATE_RE  = _re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_TIME_RE  = _re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})\s*(AM|PM|am|pm)?$")
_MONEY_RE = _re.compile(r"^\(\s*-?\$?\s*-?[\d,]+(?:\.\d+)?\s*\)$|^-?\$\s*-?[\d,]+(?:\.\d+)?$")

_SECTIONS = [
    "Style", "Fee Sheet", "Financial History", "Case information",
    "Case Type", "Court Action", "Damages", "Party List",
    "Consolidated Case Action Summary",
]
_SECTION_SET = {s.lower() for s in _SECTIONS}


def _case_key(filename: str):
    m = _CASE_RE.search(filename)
    return m.group(1).upper() if m else None


def _norm_cell(v) -> str:
    if v is None:
        return ""
    s = str(v).replace(" ", " ").strip()
    s = _re.sub(r"\s+", " ", s)
    if s == "":
        return ""

    m = _DATE_RE.match(s)
    if m:
        mo, da, yr = m.groups()
        return f"{int(mo):02d}/{int(da):02d}/{yr}"

    m = _TIME_RE.match(s)
    if m:
        hh, mm, ss, ap = m.groups()
        suf = f" {ap.upper()}" if ap else ""
        return f"{int(hh):02d}:{mm}:{ss}{suf}"

    if _MONEY_RE.match(s):
        raw = s.replace(",", "")
        neg = False
        if raw.startswith("(") and raw.endswith(")"):
            neg = True
            raw = raw[1:-1].strip()
        if raw.startswith("-"):
            neg = not neg
            raw = raw[1:].strip()
        if raw.startswith("$"):
            raw = raw[1:].strip()
        if raw.startswith("-"):
            neg = not neg
            raw = raw[1:].strip()
        try:
            val = float(raw)
            if neg:
                val = -val
            return f"${val:.2f}"
        except ValueError:
            pass

    return s


def _parse_csv_bytes(data: bytes) -> list[list[str]]:
    try:
        text = data.decode("utf-8-sig", errors="replace")
    except Exception:
        text = data.decode("latin-1", errors="replace")
    reader = _csv.reader(_io.StringIO(text))
    rows: list[list[str]] = []
    for raw in reader:
        cells = [_norm_cell(c) for c in raw]
        while cells and cells[-1] == "":
            cells.pop()
        rows.append(cells)
    return [r for r in rows if not all(c == "" for c in r)]


def _parse_sections(rows: list[list[str]]) -> dict[str, list[list[str]]]:
    sections: dict[str, list[list[str]]] = _defaultdict(list)
    current = "_preamble"
    for row in rows:
        if not row:
            continue
        first = row[0]
        if first and first.lower() in _SECTION_SET and all(c == "" for c in row[1:]):
            for canon in _SECTIONS:
                if canon.lower() == first.lower():
                    current = canon
                    break
            continue
        sections[current].append(row)
    return dict(sections)


def _row_key(row: list[str]) -> str:
    return "\t".join(row)


def _diff_sections(a: dict, b: dict) -> dict:
    result = {}
    all_secs = sorted(
        set(a) | set(b),
        key=lambda s: (_SECTIONS.index(s) if s in _SECTIONS else 999, s),
    )
    for sec in all_secs:
        ra = a.get(sec, [])
        rb = b.get(sec, [])
        ka = [_row_key(r) for r in ra]
        kb = [_row_key(r) for r in rb]
        if ka == kb:
            continue
        sa, sb = set(ka), set(kb)
        added   = [r for r in rb if _row_key(r) not in sa]
        removed = [r for r in ra if _row_key(r) not in sb]
        if not added and not removed:
            continue
        result[sec] = {"added": added, "removed": removed}
    return result


def _summarize(diff: dict) -> str:
    parts = []
    for sec, d in diff.items():
        bits = []
        if d["added"]:
            bits.append(f"+{len(d['added'])}")
        if d["removed"]:
            bits.append(f"-{len(d['removed'])}")
        parts.append(f"{sec} ({', '.join(bits)})")
    return "; ".join(parts) if parts else "no real changes"


def _group_uploads_by_case(uploaded_files) -> dict:
    """Return {case_key: (filename, bytes)}, preferring the largest file per case."""
    out: dict[str, tuple[str, bytes, int]] = {}
    for uf in uploaded_files or []:
        name = Path(uf.name).name
        if not name.lower().endswith(".csv"):
            continue
        k = _case_key(name)
        if not k:
            continue
        data = uf.getvalue()
        size = len(data)
        prev = out.get(k)
        if (prev is None) or (size > prev[2]):
            out[k] = (name, data, size)
    return {k: (v[0], v[1]) for k, v in out.items()}


def _build_excel(new_rows, mod_summary_rows, mod_detail_rows, rem_rows) -> bytes:
    wb = _openpyxl.Workbook()

    def write(name, rows, headers, color, is_first=False):
        if is_first:
            ws = wb.active
            ws.title = name
        else:
            ws = wb.create_sheet(name)
        ws.append(headers)
        for col, _ in enumerate(headers, 1):
            c = ws.cell(row=1, column=col)
            c.font = _Font(bold=True, color="FFFFFF")
            c.fill = _PatternFill("solid", fgColor=color)
            c.alignment = _Alignment(vertical="center")
        for r in rows:
            ws.append([r.get(h, "") for h in headers])
        for ci, h in enumerate(headers, 1):
            samples = [len(str(h))] + [min(len(str(r.get(h, ""))), 80) for r in rows[:300]]
            ml = max(samples) if samples else 12
            ws.column_dimensions[_openpyxl.utils.get_column_letter(ci)].width = min(max(12, ml + 2), 80)
        ws.freeze_panes = "A2"

    write("New", new_rows, ["Case Number", "File Name (End)"], "2E7D32", is_first=True)
    write("Modified (Summary)", mod_summary_rows,
          ["Case Number", "File Name (Start)", "File Name (End)", "Sections Changed", "Change Summary"],
          "1565C0")
    write("Modified (Details)", mod_detail_rows,
          ["Case Number", "File Name (End)", "Section", "Change Type", "Row Content"],
          "3949AB")
    write("No Longer In File", rem_rows, ["Case Number", "File Name (Start)"], "C62828")

    buf = _io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def render_case_folder_compare() -> None:
    st.markdown(
        """
        <div class="hub-hero">
            <h1>Case Folder Comparison</h1>
            <p>Upload a starting folder and an ending folder of case action summary CSVs.
            The tool matches files by case number (e.g. <code>SM-2025-900752</code>), normalizes
            away formatting noise (date padding, time padding, dollar-sign spacing, parens vs minus,
            CSV quoting), and reports New, Modified, and No Longer In File in one Excel workbook.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("How matching works", expanded=False):
        st.markdown(
            "- Files match by case number, not exact filename. So `10080_68-SM-2024-901842.csv` "
            "and `10080_01-SM-2024-901842.csv` are paired as the same case.\n"
            "- Supported prefixes: SM, CV, DV, CC, JU, TR, TP.\n"
            "- A case is **Modified** only when one of these sections has a real added/removed row: "
            "Fee Sheet, Financial History, Case information, Case Type, Court Action, Damages, "
            "Party List, Consolidated Case Action Summary, Style.\n"
            "- Pure formatting differences are ignored."
        )

    st.markdown('<div class="section-label">1. Upload the starting folder</div>', unsafe_allow_html=True)
    start_uploads = st.file_uploader(
        "Starting folder (older export)",
        type=["csv"],
        accept_multiple_files=True,
        help="Pick all CSVs from the starting folder, or use folder upload below.",
        key="cfc_start_files",
    )
    start_folder = st.file_uploader(
        "OR upload a whole folder",
        type=["csv"],
        accept_multiple_files="directory",
        help="Use this when your browser supports folder upload.",
        key="cfc_start_folder",
    )

    st.markdown('<div class="section-label">2. Upload the ending folder</div>', unsafe_allow_html=True)
    end_uploads = st.file_uploader(
        "Ending folder (newer export)",
        type=["csv"],
        accept_multiple_files=True,
        help="Pick all CSVs from the ending folder, or use folder upload below.",
        key="cfc_end_files",
    )
    end_folder = st.file_uploader(
        "OR upload a whole folder",
        type=["csv"],
        accept_multiple_files="directory",
        help="Use this when your browser supports folder upload.",
        key="cfc_end_folder",
    )

    start_all = list(start_uploads or []) + list(start_folder or [])
    end_all   = list(end_uploads or [])   + list(end_folder or [])

    st.markdown(
        f"""
        <div class="metric-strip">
            <div class="metric-box"><strong>{len(start_all)}</strong><span>starting CSV file(s)</span></div>
            <div class="metric-box"><strong>{len(end_all)}</strong><span>ending CSV file(s)</span></div>
            <div class="metric-box"><strong>Excel</strong><span>downloadable report</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    run = st.button("Compare folders", type="primary", use_container_width=True, disabled=not (start_all and end_all))
    if run:
        progress = st.progress(0, text="Reading starting folder...")
        start_map = _group_uploads_by_case(start_all)
        progress.progress(15, text="Reading ending folder...")
        end_map = _group_uploads_by_case(end_all)

        sk = set(start_map.keys())
        ek = set(end_map.keys())
        new_keys = sorted(ek - sk)
        rem_keys = sorted(sk - ek)
        com_keys = sorted(sk & ek)

        new_rows = [{"Case Number": k, "File Name (End)": end_map[k][0]} for k in new_keys]
        rem_rows = [{"Case Number": k, "File Name (Start)": start_map[k][0]} for k in rem_keys]
        mod_summary_rows: list[dict] = []
        mod_detail_rows:  list[dict] = []

        total = len(com_keys)
        for i, k in enumerate(com_keys, 1):
            sname, sbytes = start_map[k]
            ename, ebytes = end_map[k]
            try:
                sa = _parse_sections(_parse_csv_bytes(sbytes))
                sb = _parse_sections(_parse_csv_bytes(ebytes))
                d  = _diff_sections(sa, sb)
                if d:
                    mod_summary_rows.append({
                        "Case Number": k,
                        "File Name (Start)": sname,
                        "File Name (End)":   ename,
                        "Sections Changed":  ", ".join(d.keys()),
                        "Change Summary":    _summarize(d),
                    })
                    for sec, dd in d.items():
                        for row in dd["added"]:
                            mod_detail_rows.append({
                                "Case Number": k,
                                "File Name (End)": ename,
                                "Section": sec,
                                "Change Type": "ADDED",
                                "Row Content": " | ".join(row),
                            })
                        for row in dd["removed"]:
                            mod_detail_rows.append({
                                "Case Number": k,
                                "File Name (End)": ename,
                                "Section": sec,
                                "Change Type": "REMOVED",
                                "Row Content": " | ".join(row),
                            })
            except Exception as exc:
                mod_summary_rows.append({
                    "Case Number": k,
                    "File Name (Start)": sname,
                    "File Name (End)":   ename,
                    "Sections Changed":  "ERROR",
                    "Change Summary":    f"Read/parse error: {exc}",
                })
            if i % 10 == 0 or i == total:
                pct = 15 + int(80 * i / max(total, 1))
                progress.progress(min(pct, 95), text=f"Compared {i} of {total} common files")

        progress.progress(98, text="Building Excel report...")
        excel_bytes = _build_excel(new_rows, mod_summary_rows, mod_detail_rows, rem_rows)
        progress.progress(100, text="Done")

        st.session_state["cfc_new_rows"]     = new_rows
        st.session_state["cfc_summary_rows"] = mod_summary_rows
        st.session_state["cfc_detail_rows"]  = mod_detail_rows
        st.session_state["cfc_rem_rows"]     = rem_rows
        st.session_state["cfc_excel"]        = excel_bytes
        st.session_state["cfc_unchanged"]    = total - len(mod_summary_rows)

    if "cfc_excel" in st.session_state:
        new_rows     = st.session_state["cfc_new_rows"]
        mod_summary  = st.session_state["cfc_summary_rows"]
        mod_detail   = st.session_state["cfc_detail_rows"]
        rem_rows     = st.session_state["cfc_rem_rows"]
        unchanged    = st.session_state["cfc_unchanged"]

        st.markdown(
            f"""
            <div class="metric-strip">
                <div class="metric-box"><strong>{len(new_rows)}</strong><span>new cases</span></div>
                <div class="metric-box"><strong>{len(mod_summary)}</strong><span>modified cases ({len(mod_detail)} changes)</span></div>
                <div class="metric-box"><strong>{len(rem_rows)}</strong><span>no longer in file</span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption(
            f"{unchanged} common files had no real changes after normalization "
            "(formatting-only differences were ignored)."
        )

        st.download_button(
            "Download Excel report",
            data=st.session_state["cfc_excel"],
            file_name="Case Folder Comparison.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
        )

        tab_new, tab_mod_sum, tab_mod_det, tab_rem = st.tabs(
            ["New", "Modified (Summary)", "Modified (Details)", "No Longer In File"]
        )
        with tab_new:
            if new_rows:
                st.dataframe(new_rows, use_container_width=True, hide_index=True)
            else:
                st.info("No new cases.")
        with tab_mod_sum:
            if mod_summary:
                st.dataframe(mod_summary, use_container_width=True, hide_index=True)
            else:
                st.info("No modified cases.")
        with tab_mod_det:
            if mod_detail:
                st.dataframe(mod_detail, use_container_width=True, hide_index=True)
            else:
                st.info("No individual changes to show.")
        with tab_rem:
            if rem_rows:
                st.dataframe(rem_rows, use_container_width=True, hide_index=True)
            else:
                st.info("No removed cases.")


def render_beam_pdf_splitter() -> None:
    st.markdown(
        """
        <div class="hub-hero">
            <h1>Beam PDF Splitter</h1>
            <p>Upload a PDF or a folder of PDFs, review every two-page chunk, fix any missing beam numbers, and download a clean ZIP of renamed files.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("Processing rules", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            include_odd_final_page = st.checkbox("Include odd final page as a single-page PDF", value=False)
        with col2:
            use_fallback_names = st.checkbox("Use fallback name if beam number is not found", value=False)

    st.markdown('<div class="section-label">Upload PDFs</div>', unsafe_allow_html=True)
    upload_tabs = st.tabs(["Single or multiple PDF files", "Folder of PDFs"])
    with upload_tabs[0]:
        file_uploads = st.file_uploader(
            "Choose one PDF or several PDFs",
            type=["pdf"],
            accept_multiple_files=True,
            help="Use this when you have one PDF or a few PDFs selected manually.",
            key="beam_pdf_file_uploads",
        )
    with upload_tabs[1]:
        folder_uploads = st.file_uploader(
            "Choose a folder",
            type=["pdf"],
            accept_multiple_files="directory",
            help="Use this when you want to upload all PDFs from a folder.",
            key="beam_pdf_folder_uploads",
        )

    uploaded_files = list(file_uploads or []) + list(folder_uploads or [])
    upload_signature = uploaded_files_signature(uploaded_files)
    if st.session_state.get("beam_upload_signature") != upload_signature:
        st.session_state["beam_upload_signature"] = upload_signature
        st.session_state["beam_zip_bytes"] = None
        st.session_state["beam_result_rows"] = []
        st.session_state["beam_result_logs"] = []

    if not uploaded_files:
        left, right = st.columns(2)
        with left:
            st.markdown(
                """
                <div class="tool-card">
                    <h3>What it does</h3>
                    <p>Splits page pairs like 1-2, 3-4, 5-6 and names each output from the beam number at the bottom of the second page.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with right:
            st.markdown(
                """
                <div class="tool-card">
                    <h3>Review before download</h3>
                    <p>If OCR misses a beam number, edit the filename in the review table before creating the ZIP.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        return

    expected_pairs = 0
    for uploaded_file in uploaded_files:
        try:
            with fitz.open(stream=uploaded_file.getvalue(), filetype="pdf") as doc:
                expected_pairs += doc.page_count // 2
        except Exception:
            pass

    st.markdown(
        f"""
        <div class="metric-strip">
            <div class="metric-box"><strong>{len(uploaded_files)}</strong><span>PDF upload(s)</span></div>
            <div class="metric-box"><strong>{expected_pairs}</strong><span>two-page output file(s)</span></div>
            <div class="metric-box"><strong>ZIP</strong><span>renamed download</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.caption("After upload, click the button below. The app will create one renamed PDF for each two-page pair.")

    if st.button("Split and Rename PDFs", type="primary", use_container_width=True):
        progress = st.progress(0, text="Splitting PDFs...")
        try:
            zip_bytes, result_rows, logs = split_and_rename_pdfs(uploaded_files, include_odd_final_page, use_fallback_names)
            st.session_state["beam_zip_bytes"] = zip_bytes
            st.session_state["beam_result_rows"] = result_rows
            st.session_state["beam_result_logs"] = logs
            progress.progress(100, text="Finished")
        except Exception as exc:
            st.session_state["beam_zip_bytes"] = None
            st.session_state["beam_result_rows"] = []
            st.session_state["beam_result_logs"] = [f"Processing failed: {exc}"]
            progress.progress(100, text="Failed")

    result_rows = st.session_state.get("beam_result_rows", [])
    logs = st.session_state.get("beam_result_logs", [])

    if logs:
        with st.expander("Processing log", expanded=True):
            for log in logs:
                st.write(log)
        if not st.session_state.get("beam_zip_bytes"):
            st.error("No download was created. Check the processing log above.")

    if result_rows:
        st.subheader("Created Files")
        st.dataframe(result_rows, use_container_width=True, hide_index=True)

    if st.session_state.get("beam_zip_bytes"):
        st.success("Your split and renamed PDFs are ready.")
        st.download_button(
            "Download Beam Split Results",
            data=st.session_state["beam_zip_bytes"],
            file_name="beam_split_results.zip",
            mime="application/zip",
            type="primary",
            use_container_width=True,
        )


def render_home(tools: list[ToolDefinition]) -> None:
    st.markdown(
        """
        <div class="hub-hero">
            <h1>Resolution Law Tools</h1>
            <p>A clean web toolbox for PDF, document, and office workflows. Start with Beam PDF Splitter, then add more tools as the team needs them.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.subheader("Available Tools")
    columns = st.columns(2)
    for index, tool in enumerate(tools):
        with columns[index % 2]:
            st.markdown(
                f"""
                <div class="tool-card clickable">
                    <h3>{tool.name}</h3>
                    <p>{tool.description}</p>
                    <p class="small-muted">{tool.category} tool</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button(tool.name, key=f"open_{tool.tool_id}", use_container_width=True):
                st.session_state["active_tool_label"] = tool.name
                st.rerun()

    st.info("Future tools can be added by adding another render function and ToolDefinition in app.py.")


def render_future_tools_guide() -> None:
    st.markdown(
        """
        <div class="hub-hero">
            <h1>Add Future Tools</h1>
            <p>Resolution Law Tools is set up as a toolbox. Add another workflow by creating a render function and registering it in the tools list.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.write("Add a new function like this:")
    st.code(
        '''def render_new_tool() -> None:
    st.markdown("""
    <div class="hub-hero">
        <h1>New Tool</h1>
        <p>Short description of what this tool does.</p>
    </div>
    """, unsafe_allow_html=True)
    st.write("Build the workflow here.")
''',
        language="python",
    )

    st.write("Then add a registry entry:")
    st.code(
        '''ToolDefinition(
    tool_id="new-tool",
    name="New Tool",
    category="Documents",
    description="Short plain-English description.",
    render=render_new_tool,
)''',
        language="python",
    )


def get_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            tool_id="beam-pdf-splitter",
            name="Beam PDF Splitter",
            category="PDF",
            description="Split PDFs into two-page chunks and name each output from the beam number in the footer.",
            render=render_beam_pdf_splitter,
        ),
        ToolDefinition(
            tool_id="case-folder-compare",
            name="Case Folder Comparison",
            category="Documents",
            description="Compare two folders of case action summary CSVs. Detect new, modified, and removed cases; ignore formatting-only differences.",
            render=render_case_folder_compare,
        ),
    ]


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    inject_css()

    tools = get_tools()
    menu_options = ["Home"] + [tool.name for tool in tools] + ["Add Future Tools"]
    active_label = st.session_state.get("active_tool_label", "Home")
    if active_label not in menu_options:
        active_label = "Home"

    with st.sidebar:
        st.title(APP_TITLE)
        selected_label = st.radio(
            "Tools",
            menu_options,
            index=menu_options.index(active_label),
            label_visibility="collapsed",
        )
        st.session_state["active_tool_label"] = selected_label
        st.divider()
        st.caption("Upload files, process them in the browser app, then download results.")

    if selected_label == "Home":
        render_home(tools)
        return

    if selected_label == "Add Future Tools":
        render_future_tools_guide()
        return

    selected_tool = next(tool for tool in tools if tool.name == selected_label)
    selected_tool.render()


if __name__ == "__main__":
    main()
