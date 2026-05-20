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


def find_beam_number_in_text(text: str) -> str | None:
    if not text:
        return None

    normalized = text.replace(",", "")
    tokens = re.findall(r"\b\d{2,}\b", normalized)
    if tokens:
        return tokens[-1]

    digits_only = re.sub(r"\D", "", normalized)
    if len(digits_only) >= 2:
        return digits_only

    return None


def extract_beam_number_from_page(
    page,
    use_ocr: bool,
    ocr_error_callback: Callable[[Exception], None] | None = None,
) -> tuple[str | None, str]:
    page_rect = page.rect
    footer_rect = fitz.Rect(0, page_rect.height * FOOTER_TOP_RATIO, page_rect.width, page_rect.height)

    text = page.get_text("text", clip=footer_rect) or ""
    beam = find_beam_number_in_text(text)
    if beam:
        return beam, "native text"

    if not use_ocr:
        return None, "not found"

    try:
        from PIL import Image, ImageOps
        import pytesseract

        configure_tesseract(pytesseract)
        matrix = fitz.Matrix(3, 3)
        pixmap = page.get_pixmap(matrix=matrix, clip=footer_rect, alpha=False)
        image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
        image = ImageOps.autocontrast(ImageOps.grayscale(image))
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
            odd_page_mode = st.radio(
                "Odd final page",
                ["Include as single-page output", "Skip odd final pages", "Review odd final pages"],
            )
        with col2:
            missing_beam_mode = st.radio(
                "Missing beam number",
                ["Review before download", "Use fallback names", "Skip missing beam pairs"],
            )

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

    st.markdown(
        f"""
        <div class="metric-strip">
            <div class="metric-box"><strong>{len(uploaded_files)}</strong><span>PDF upload(s)</span></div>
            <div class="metric-box"><strong>Review</strong><span>edit names before download</span></div>
            <div class="metric-box"><strong>ZIP</strong><span>download output</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Analyze PDFs", type="primary", use_container_width=True):
        progress = st.progress(0, text="Reading PDFs...")
        rows, logs, file_bytes = analyze_uploads(uploaded_files, odd_page_mode, missing_beam_mode)
        progress.progress(100, text="Analysis complete")
        st.session_state["beam_analysis_rows"] = rows
        st.session_state["beam_analysis_logs"] = logs
        st.session_state["beam_file_bytes"] = file_bytes
        st.session_state["beam_zip_bytes"] = None

    rows = st.session_state.get("beam_analysis_rows")
    if not rows:
        return

    logs = st.session_state.get("beam_analysis_logs", [])
    included_count = sum(1 for row in rows if row.get("include"))
    issue_count = sum(1 for row in rows if row.get("issue"))
    st.info(f"Analysis found {len(rows)} chunk row(s), with {included_count} currently selected for output.")

    if logs:
        with st.expander("Processing log", expanded=bool(issue_count)):
            for log in logs:
                st.write(log)

    st.subheader("Review Output Names")
    edited_rows = st.data_editor(
        rows,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        disabled=["row_id", "source_file", "pages", "start_page", "end_page", "detected_beam", "method", "issue"],
        column_config={
            "row_id": None,
            "start_page": None,
            "end_page": None,
            "include": st.column_config.CheckboxColumn("Include"),
            "source_file": st.column_config.TextColumn("Source PDF"),
            "pages": st.column_config.TextColumn("Pages"),
            "detected_beam": st.column_config.TextColumn("Detected beam"),
            "filename_stem": st.column_config.TextColumn("Output filename"),
            "method": st.column_config.TextColumn("Method"),
            "issue": st.column_config.TextColumn("Status"),
        },
        key="beam_review_editor",
    )

    create_zip = st.button("Create Download ZIP", type="primary", use_container_width=True)
    if create_zip:
        zip_bytes, errors = build_zip(edited_rows, st.session_state.get("beam_file_bytes", {}))
        if errors:
            st.error("Fix these items before downloading:")
            for error in errors:
                st.write(f"- {error}")
        else:
            st.session_state["beam_zip_bytes"] = zip_bytes
            st.success("ZIP is ready.")

    if st.session_state.get("beam_zip_bytes"):
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
