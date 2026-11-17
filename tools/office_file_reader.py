"""
title: Office File Reader
description: 讀取使用者上傳的 Office 與開源格式附件（Word、Excel、PowerPoint、PDF、ODT/ODS/ODP、CSV、文字檔等），轉成 Markdown 讓模型閱讀
version: 1.0.0
license: MIT
requirements: python-docx, openpyxl, python-pptx, pypdf, pdfplumber, odfpy, xlrd
"""

import asyncio
import csv
import email
import inspect
import io
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import date, datetime, time
from email import policy
from html.parser import HTMLParser
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 副檔名分類
# ---------------------------------------------------------------------------

WORD_EXT = {".docx", ".docm"}
EXCEL_EXT = {".xlsx", ".xlsm"}
PPT_EXT = {".pptx", ".pptm"}
LEGACY_TO_MODERN = {  # 舊格式先用 LibreOffice 轉成新格式再讀
    ".doc": "docx",
    ".rtf": "docx",
    ".wps": "docx",
    ".ppt": "pptx",
    ".pps": "pptx",
}
SHEET_EXT = {".xlsx", ".xlsm", ".xls", ".ods", ".csv", ".tsv"}
TEXT_EXT = {
    ".txt", ".md", ".log", ".sql", ".json", ".xml", ".yaml", ".yml", ".ini",
    ".conf", ".cfg", ".properties", ".ktr", ".kjb", ".java", ".js", ".ts",
    ".py", ".sh", ".bat", ".cmd", ".ps1", ".jsp", ".css", ".cs", ".vb",
    ".pls", ".pks", ".pkb", ".prc", ".fnc", ".trg", ".vw",
}
HTML_EXT = {".html", ".htm"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}

TEXT_ENCODINGS = ("utf-8-sig", "cp950", "big5hkscs", "gb18030")


# ---------------------------------------------------------------------------
# 共用小工具
# ---------------------------------------------------------------------------

def _decode_bytes(raw: bytes) -> str:
    """依序嘗試 UTF-8、Big5（cp950）、GB18030，都失敗就以 UTF-8 取代無法解碼的字元。"""
    for enc in TEXT_ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _read_text(path: str) -> str:
    with open(path, "rb") as f:
        return _decode_bytes(f.read())


def _cell_str(value: Any, number_format: str = "") -> str:
    """把儲存格的值轉成字串：日期去掉 00:00:00、整數去掉 .0、依格式補回前導 0。"""
    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.time() == time(0, 0):
            return value.strftime("%Y-%m-%d")
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int) and number_format and re.fullmatch(r"0+", number_format):
        return str(value).zfill(len(number_format))  # 例如工號格式 00000
    return str(value)


def _md_escape(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _md_table(rows: list) -> str:
    """把二維清單轉成 Markdown 表格，第一列當標題。"""
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        return "（空表格）"
    width = max(len(r) for r in rows)
    norm = [[_md_escape(c) for c in r] + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(norm[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in norm[1:]]
    return "\n".join(lines)


def _trim_rows(rows: list) -> list:
    """去掉每列尾端與整張表尾端的空白儲存格。"""
    out = []
    for r in rows:
        r = list(r)
        while r and str(r[-1]).strip() == "":
            r.pop()
        out.append(r)
    while out and not out[-1]:
        out.pop()
    return out


# ---------------------------------------------------------------------------
# LibreOffice 轉檔（舊版 .doc / .ppt / .rtf，以及其他格式的備援）
# ---------------------------------------------------------------------------

def _soffice_convert(path: str, target: str, soffice: str, timeout: int = 120) -> str:
    exe = shutil.which(soffice) or (soffice if os.path.exists(soffice) else None)
    if not exe:
        raise RuntimeError(
            "伺服器沒有安裝 LibreOffice，無法讀取此舊版格式。請使用者另存為 .docx / .xlsx / .pptx 後重新上傳"
        )
    outdir = tempfile.mkdtemp(prefix="ofr_")
    profile = tempfile.mkdtemp(prefix="ofr_profile_")
    cmd = [
        exe, "--headless", "--norestore", "--nologo",
        f"-env:UserInstallation=file://{profile}",
        "--convert-to", target, "--outdir", outdir, path,
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout, check=False)
    shutil.rmtree(profile, ignore_errors=True)
    base = os.path.splitext(os.path.basename(path))[0]
    for f in os.listdir(outdir):
        if f.startswith(base) and f.lower().endswith("." + target.split(":")[0]):
            return os.path.join(outdir, f)
    raise RuntimeError(f"LibreOffice 轉檔失敗（{os.path.basename(path)} → {target}）")


# ---------------------------------------------------------------------------
# 各格式轉 Markdown
# ---------------------------------------------------------------------------

def _docx_to_md(path: str) -> str:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = docx.Document(path)
    out = []
    for el in doc.element.body.iterchildren():
        tag = el.tag.split("}")[-1]
        if tag == "p":
            p = Paragraph(el, doc)
            text = p.text.strip()
            if not text:
                continue
            style = (p.style.name if p.style is not None else "") or ""
            m = re.search(r"(?:Heading|標題)\s*(\d)", style)
            if m:
                out.append("#" * min(int(m.group(1)) + 1, 6) + " " + text)
            elif style == "Title":
                out.append("# " + text)
            elif "List" in style or "清單" in style:
                out.append("- " + text)
            else:
                out.append(text)
        elif tag == "tbl":
            t = Table(el, doc)
            rows = [[c.text for c in r.cells] for r in t.rows]
            out.append(_md_table(rows))
    return "\n\n".join(out)


def _pptx_to_md(path: str) -> str:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    prs = Presentation(path)
    out = []

    def walk(shapes, lines):
        for sh in shapes:
            if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
                walk(sh.shapes, lines)
                continue
            if getattr(sh, "has_table", False) and sh.has_table:
                rows = [[c.text for c in r.cells] for r in sh.table.rows]
                lines.append(_md_table(rows))
            elif getattr(sh, "has_text_frame", False) and sh.has_text_frame:
                for para in sh.text_frame.paragraphs:
                    t = "".join(r.text for r in para.runs).strip()
                    if t:
                        lines.append(("  " * para.level) + "- " + t)

    for i, slide in enumerate(prs.slides, 1):
        title = ""
        if slide.shapes.title is not None and slide.shapes.title.has_text_frame:
            title = slide.shapes.title.text_frame.text.strip()
        lines = []
        walk([s for s in slide.shapes if s != slide.shapes.title], lines)
        out.append(f"## 投影片 {i}" + (f"：{title}" if title else ""))
        out.extend(lines)
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                out.append("> 備註：" + notes.replace("\n", " "))
    return "\n\n".join(out)


def _pdf_to_md(path: str) -> str:
    """優先用 pdfplumber（可辨識有框線的表格），失敗時改用 pypdf 只擷取文字。"""
    try:
        import pdfplumber
    except ImportError:
        return _pdf_to_md_text_only(path)
    try:
        return _pdf_to_md_with_tables(pdfplumber, path)
    except Exception:
        return _pdf_to_md_text_only(path)  # 加密、格式異常等情況交給 pypdf 處理並回報原因


def _pdf_to_md_with_tables(pdfplumber, path: str) -> str:
    out, total_chars = [], 0
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            items = []  # (上緣位置, 內容)，依由上到下排序
            boxes = []
            for tb in page.find_tables():
                rows = [[c or "" for c in r] for r in tb.extract()]
                # 只有一列或一欄的通常是誤判的外框，當成一般文字處理
                if len(rows) < 2 or max((len(r) for r in rows), default=0) < 2:
                    continue
                boxes.append(tb.bbox)
                items.append((tb.bbox[1], _md_table(rows)))

            def outside(obj, boxes=boxes):
                cx = (obj["x0"] + obj["x1"]) / 2
                cy = (obj["top"] + obj["bottom"]) / 2
                return not any(x0 <= cx <= x1 and top <= cy <= bottom for x0, top, x1, bottom in boxes)

            text_page = page.filter(outside) if boxes else page
            for line in text_page.extract_text_lines():
                t = line["text"].strip()
                if t:
                    items.append((line["top"], t))
            items.sort(key=lambda x: x[0])
            # 表格前後空一行，Markdown 才會正確顯示
            body = "\n".join(f"\n{c}\n" if c.startswith("|") else c for _, c in items).strip()
            total_chars += sum(len(c) for _, c in items)
            out.append(f"## 第 {i} 頁\n\n{body if body else '（此頁沒有可擷取的文字）'}")
        n_pages = len(pdf.pages)

    md = "\n\n".join(out)
    if n_pages and total_chars / n_pages < 20:
        md = (
            "> ⚠️ 這份 PDF 幾乎沒有文字層，可能是掃描檔或圖片，需要 OCR 才能讀取內容。"
            "請告知使用者改提供文字版或 Word 檔。\n\n" + md
        )
    return md


def _pdf_to_md_text_only(path: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(path)
    if reader.is_encrypted:
        try:
            ok = reader.decrypt("")  # 只有「開啟不需密碼、僅限制編輯」的 PDF 能用空密碼解開
        except Exception:
            ok = 0
        if not ok:
            raise RuntimeError("PDF 有密碼保護，無法讀取。請使用者提供未加密的檔案")
    out, total_chars = [], 0
    for i, page in enumerate(reader.pages, 1):
        text = (page.extract_text() or "").strip()
        total_chars += len(text)
        out.append(f"## 第 {i} 頁\n\n{text if text else '（此頁沒有可擷取的文字）'}")
    md = "\n\n".join(out)
    if reader.pages and total_chars / len(reader.pages) < 20:
        md = (
            "> ⚠️ 這份 PDF 幾乎沒有文字層，可能是掃描檔或圖片，需要 OCR 才能讀取內容。"
            "請告知使用者改提供文字版或 Word 檔。\n\n" + md
        )
    return md


def _odf_text(node) -> str:
    from odf import teletype
    return teletype.extractText(node).strip()


def _odt_to_md(path: str) -> str:
    from odf.opendocument import load
    from odf.namespaces import TABLENS, TEXTNS

    doc = load(path)
    out = []

    def walk(node, depth=0):
        for child in node.childNodes:
            if child.nodeType != child.ELEMENT_NODE:
                continue
            ns, name = child.qname
            if ns == TEXTNS and name == "h":
                level = int(child.getAttrNS(TEXTNS, "outline-level") or 1)
                out.append("#" * min(level + 1, 6) + " " + _odf_text(child))
            elif ns == TEXTNS and name == "p":
                t = _odf_text(child)
                if t:
                    out.append(t)
            elif ns == TEXTNS and name == "list":
                for item in child.childNodes:
                    if item.nodeType == item.ELEMENT_NODE and item.qname[1] == "list-item":
                        t = _odf_text(item)
                        if t:
                            out.append("  " * depth + "- " + t)
            elif ns == TABLENS and name == "table":
                out.append(_md_table(_ods_table_rows(child)))
            else:
                walk(child, depth)

    walk(doc.text)
    return "\n\n".join(out)


def _odp_to_md(path: str) -> str:
    from odf.opendocument import load
    from odf.namespaces import DRAWNS, PRESENTATIONNS, TABLENS, TEXTNS
    from odf import draw
    from odf.text import P

    doc = load(path)
    out = []

    def frames(node):
        """投影片上的文字框與表格（含群組內的），不含備註頁。"""
        for child in node.childNodes:
            if child.nodeType != child.ELEMENT_NODE:
                continue
            if child.qname == (DRAWNS, "frame"):
                yield child
            elif child.qname == (DRAWNS, "g"):
                yield from frames(child)

    def paragraphs(node):
        return [_odf_text(p) for p in node.getElementsByType(P)]

    for i, page in enumerate(doc.getElementsByType(draw.Page), 1):
        title, lines = "", []
        for fr in frames(page):
            cls = fr.getAttrNS(PRESENTATIONNS, "class") or ""
            tables = [c for c in fr.childNodes if getattr(c, "qname", None) == (TABLENS, "table")]
            if tables:
                lines.append(_md_table(_ods_table_rows(tables[0])))
            elif cls == "title" and not title:
                title = " ".join(t for t in paragraphs(fr) if t)
            elif cls not in ("page-number", "date-time", "footer", "header"):
                lines.extend("- " + t for t in paragraphs(fr) if t)
        out.append(f"## 投影片 {i}" + (f"：{title}" if title else ""))
        out.extend(lines)
        for notes in page.childNodes:
            if getattr(notes, "qname", None) != (PRESENTATIONNS, "notes"):
                continue
            texts = [
                t for fr in notes.getElementsByType(draw.Frame)
                if (fr.getAttrNS(PRESENTATIONNS, "class") or "") == "notes"
                for t in paragraphs(fr) if t
            ]
            if texts:
                out.append("> 備註：" + " ".join(texts))
    return "\n\n".join(out)


def _html_to_md(path: str) -> str:
    class _P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts, self.skip = [], 0

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style"):
                self.skip += 1
            if tag in ("p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table"):
                self.parts.append("\n")
            if tag in ("td", "th"):
                self.parts.append(" | ")

        def handle_endtag(self, tag):
            if tag in ("script", "style"):
                self.skip -= 1

        def handle_data(self, data):
            if not self.skip:
                self.parts.append(data)

    p = _P()
    p.feed(_read_text(path))
    text = re.sub(r"[ \t]+", " ", "".join(p.parts))
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _eml_to_md(path: str) -> str:
    with open(path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=policy.default)
    fields = [("主旨", "subject"), ("寄件者", "from"), ("收件者", "to"), ("副本", "cc"), ("日期", "date")]
    out = [f"**{label}**：{msg.get(key)}" for label, key in fields if msg.get(key)]
    body = msg.get_body(preferencelist=("plain", "html"))
    if body is not None:
        content = body.get_content()
        if body.get_content_type() == "text/html":
            content = re.sub(r"<[^>]+>", " ", content)
        out.append("\n" + content.strip())
    names = [part.get_filename() for part in msg.iter_attachments() if part.get_filename()]
    if names:
        out.append("**信件附件**：" + "、".join(names))
    return "\n\n".join(out)


def _zip_to_md(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        names = [i.filename for i in z.infolist() if not i.is_dir()]
    return "壓縮檔內容（未解壓縮，請使用者解壓縮後上傳需要的檔案）：\n\n" + "\n".join("- " + n for n in names)


# ---------------------------------------------------------------------------
# 試算表：讀成 {工作表名稱: 二維清單}
# ---------------------------------------------------------------------------

def _ods_table_rows(table, max_rows: int = 1_000_000) -> list:
    from odf.namespaces import OFFICENS, TABLENS

    rows = []
    for row in table.childNodes:
        if row.nodeType != row.ELEMENT_NODE:
            continue
        if row.qname[1] == "table-header-rows" or row.qname[1] == "table-row-group":
            rows.extend(_ods_table_rows(row, max_rows))
            continue
        if row.qname[1] != "table-row":
            continue
        cells = []
        for cell in row.childNodes:
            if cell.nodeType != cell.ELEMENT_NODE or cell.qname[1] not in ("table-cell", "covered-table-cell"):
                continue
            vtype = cell.getAttrNS(OFFICENS, "value-type")
            text = _odf_text(cell)
            if vtype == "date":
                text = (cell.getAttrNS(OFFICENS, "date-value") or text).replace("T00:00:00", "")
            rep = int(cell.getAttrNS(TABLENS, "number-columns-repeated") or 1)
            cells.extend([text] * min(rep, 1024))
        rrep = int(row.getAttrNS(TABLENS, "number-rows-repeated") or 1)
        if not any(c.strip() for c in cells):
            rrep = min(rrep, 1)  # 大量重複的空白列只保留一列
        for _ in range(min(rrep, max_rows)):
            rows.append(list(cells))
        if len(rows) >= max_rows:
            break
    return _trim_rows(rows)


def _load_sheets(path: str, ext: str) -> dict:
    sheets = {}
    if ext in (".xlsx", ".xlsm"):
        import openpyxl

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        for ws in wb.worksheets:
            rows = [[_cell_str(c.value, getattr(c, "number_format", "") or "") for c in r] for r in ws.iter_rows()]
            sheets[ws.title] = _trim_rows(rows)
        wb.close()
    elif ext == ".xls":
        import xlrd

        book = xlrd.open_workbook(path, formatting_info=True)

        def fmt(cell):
            try:
                return book.format_map[book.xf_list[cell.xf_index].format_key].format_str
            except (IndexError, KeyError, AttributeError):
                return ""

        for sh in book.sheets():
            rows = []
            for r in range(sh.nrows):
                row = []
                for c in range(sh.ncols):
                    cell = sh.cell(r, c)
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        row.append(_cell_str(xlrd.xldate_as_datetime(cell.value, book.datemode)))
                    else:
                        row.append(_cell_str(cell.value, fmt(cell)))
                rows.append(row)
            sheets[sh.name] = _trim_rows(rows)
    elif ext == ".ods":
        from odf.opendocument import load
        from odf.namespaces import TABLENS
        from odf.table import Table

        doc = load(path)
        for t in doc.spreadsheet.getElementsByType(Table):
            sheets[t.getAttrNS(TABLENS, "name")] = _ods_table_rows(t)
    elif ext in (".csv", ".tsv"):
        text = _read_text(path)
        if ext == ".tsv":
            delim = "\t"
        else:
            try:
                delim = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|").delimiter
            except csv.Error:
                delim = ","
        sheets[os.path.basename(path)] = _trim_rows(list(csv.reader(io.StringIO(text), delimiter=delim)))
    return sheets


def _sheets_to_md(sheets: dict, preview_rows: int) -> str:
    out = []
    for name, rows in sheets.items():
        ncols = max((len(r) for r in rows), default=0)
        head = f"## 工作表：{name}（共 {len(rows)} 列、{ncols} 欄）"
        if not rows:
            out.append(head + "\n\n（空白工作表）")
            continue
        shown = rows[: preview_rows + 1]  # +1 是標題列
        body = _md_table(shown)
        if len(rows) > len(shown):
            body += (
                f"\n\n> 只顯示前 {len(shown) - 1} 筆資料，還有 {len(rows) - len(shown)} 列。"
                f"請用 read_spreadsheet 指定 sheet_name=\"{name}\" 與 start_row 繼續讀取。"
            )
        out.append(head + "\n\n" + body)
    return "\n\n".join(out)


# ---------------------------------------------------------------------------
# 總入口：任何檔案 → Markdown
# ---------------------------------------------------------------------------

def convert_to_markdown(path: str, filename: str, preview_rows: int = 100, soffice: str = "soffice") -> str:
    ext = os.path.splitext(filename or path)[1].lower()
    if ext in WORD_EXT:
        return _docx_to_md(path)
    if ext in EXCEL_EXT or ext in (".xls", ".ods", ".csv", ".tsv"):
        try:
            return _sheets_to_md(_load_sheets(path, ext), preview_rows)
        except ImportError:
            raise
        except Exception:
            if ext == ".xls":  # 部分 .xls 其實是 HTML 或新格式，改用 LibreOffice 轉
                return _sheets_to_md(_load_sheets(_soffice_convert(path, "xlsx", soffice), ".xlsx"), preview_rows)
            raise
    if ext in PPT_EXT:
        return _pptx_to_md(path)
    if ext == ".pdf":
        return _pdf_to_md(path)
    if ext == ".odt":
        return _odt_to_md(path)
    if ext == ".odp":
        return _odp_to_md(path)
    if ext in LEGACY_TO_MODERN:
        target = LEGACY_TO_MODERN[ext]
        converted = _soffice_convert(path, target, soffice)
        return _docx_to_md(converted) if target == "docx" else _pptx_to_md(converted)
    if ext in HTML_EXT:
        return _html_to_md(path)
    if ext == ".eml":
        return _eml_to_md(path)
    if ext == ".zip":
        return _zip_to_md(path)
    if ext in IMAGE_EXT:
        return (
            "這是圖片檔，本工具無法讀取圖片中的文字。"
            "若模型支援看圖請直接看圖；否則請使用者把圖片中的文字貼上。"
        )
    if ext in TEXT_EXT or ext == "":
        return _read_text(path)
    # 未知格式：能當文字讀就當文字讀
    with open(path, "rb") as f:
        head = f.read(4096)
    if b"\x00" in head:
        raise RuntimeError(f"不支援的檔案格式（{ext}），請使用者轉成 PDF、Word、Excel 或文字檔")
    return _read_text(path)


def _split_parts(text: str, max_chars: int) -> list:
    """依字數切段，盡量在換行處切開。"""
    parts, start = [], 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            cut = text.rfind("\n", start + max_chars // 2, end)
            if cut > start:
                end = cut
        parts.append(text[start:end])
        start = end
    # 表格被切開時，在後面幾段補上表格標題列，模型才知道每一欄是什麼
    for i in range(1, len(parts)):
        body = parts[i].lstrip("\n")
        if not body.startswith("|"):
            continue
        before = "".join(parts[:i]).splitlines()
        for j in range(len(before) - 1, 0, -1):
            if before[j].startswith("|---"):
                parts[i] = f"（接續上一段的表格）\n\n{before[j - 1]}\n{before[j]}\n{body}"
                break
    return parts or [""]


# ---------------------------------------------------------------------------
# Open WebUI 工具
# ---------------------------------------------------------------------------

class Tools:
    class Valves(BaseModel):
        MAX_CHARS: int = Field(default=12000, description="read_attachment 每次回傳的最大字數，依模型 context 長度調整")
        PREVIEW_ROWS: int = Field(default=100, description="read_attachment 每個工作表最多顯示幾筆資料")
        MAX_ROWS: int = Field(default=200, description="read_spreadsheet 每次最多回傳幾列")
        SOFFICE_PATH: str = Field(default="soffice", description="LibreOffice 執行檔路徑，讀取 .doc/.ppt/.rtf 時使用")

    def __init__(self):
        self.valves = self.Valves()
        self._cache = {}  # (path, mtime) -> markdown

    # ---- 取得附件 -----------------------------------------------------------

    @staticmethod
    def _entries(files: Optional[list]) -> list:
        out = []
        for item in files or []:
            if not isinstance(item, dict):
                continue
            f = item.get("file") or {}
            meta = f.get("meta") or {}
            fid = item.get("id") or f.get("id") or ""
            out.append({
                "id": fid,
                "name": item.get("name") or item.get("filename") or f.get("filename") or meta.get("name") or fid,
                "path": f.get("path") or item.get("path"),  # 只在沒有 Open WebUI 的測試環境使用
                "type": item.get("type") or "file",
                "size": item.get("size") or meta.get("size"),
                "content_type": meta.get("content_type") or item.get("content_type") or "",
            })
        return out

    @staticmethod
    async def _maybe_await(value):
        return await value if inspect.isawaitable(value) else value

    async def _can_read(self, rec, user: Optional[dict]) -> bool:
        if not user:
            return False
        if rec.user_id == user.get("id") or user.get("role") == "admin":
            return True
        try:  # 共用給使用者的檔案（較新版 Open WebUI 才有）
            from open_webui.models.users import UserModel
            from open_webui.utils.access_control.files import has_access_to_file

            return bool(await self._maybe_await(
                has_access_to_file(file_id=rec.id, access_type="read", user=UserModel(**user))
            ))
        except Exception:
            return False

    async def _local_path(self, entry: dict, user: Optional[dict]) -> str:
        try:
            from open_webui.models.files import Files
            from open_webui.storage.provider import Storage
        except ImportError:
            # 不在 Open WebUI 中執行（例如本機測試）才直接使用路徑
            path = entry.get("path")
            if path and os.path.exists(path):
                return path
            raise RuntimeError("找不到附件的檔案位置")

        # __files__ 來自前端請求，不可信任其中的 path，一律從資料庫查檔案並檢查權限
        if not entry.get("id"):
            raise RuntimeError("找不到附件的檔案 ID")
        rec = await self._maybe_await(Files.get_file_by_id(entry["id"]))
        if rec is None or not rec.path:
            raise RuntimeError("附件已不存在，請使用者重新上傳")
        if not await self._can_read(rec, user):
            raise PermissionError("沒有權限讀取這個附件")
        return await self._maybe_await(Storage.get_file(rec.path))

    def _pick(self, files: Optional[list], file_name: str) -> dict:
        entries = [
            e for e in self._entries(files)
            if e["type"] == "file" and e["id"] and not str(e["id"]).startswith(("http://", "https://", "data:"))
        ]
        if not entries:
            raise RuntimeError("這則對話沒有可讀取的附件。請使用者重新上傳檔案")
        if not file_name:
            if len(entries) == 1:
                return entries[0]
            raise RuntimeError("有多個附件，請指定 file_name：" + "、".join(e["name"] for e in entries))
        for test in (
            lambda e: e["name"] == file_name,
            lambda e: e["name"].lower() == file_name.lower(),
            lambda e: file_name.lower() in e["name"].lower(),
        ):
            hits = [e for e in entries if test(e)]
            if len(hits) == 1:
                return hits[0]
        raise RuntimeError(f"找不到名為「{file_name}」的附件。目前的附件：" + "、".join(e["name"] for e in entries))

    async def _markdown(self, entry: dict, user: Optional[dict]) -> str:
        path = await self._local_path(entry, user)
        key = (path, os.path.getmtime(path), self.valves.PREVIEW_ROWS)
        if key not in self._cache:
            if len(self._cache) >= 20:  # 只保留最近 20 份轉檔結果
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = await asyncio.to_thread(
                convert_to_markdown, path, entry["name"], self.valves.PREVIEW_ROWS, self.valves.SOFFICE_PATH
            )
        return self._cache[key]

    @staticmethod
    async def _status(emitter, text: str, done: bool = False):
        if emitter:
            await emitter({"type": "status", "data": {"description": text, "done": done}})

    # ---- 提供給模型的工具 -----------------------------------------------------

    async def list_attachments(self, __files__: Optional[list] = None) -> str:
        """
        列出使用者在這則對話上傳的所有附件（檔名、類型、大小）。
        有附件時先呼叫這個工具，確認有哪些檔案，再決定用哪個工具讀取。
        """
        entries = self._entries(__files__)
        if not entries:
            return "這則對話沒有附件。"
        lines = ["目前的附件："]
        for e in entries:
            ext = os.path.splitext(e["name"])[1].lower()
            kind = "試算表（可用 read_spreadsheet）" if ext in SHEET_EXT else (
                "圖片" if ext in IMAGE_EXT else ("知識庫" if e["type"] == "collection" else "文件"))
            size = f"，{int(e['size']) // 1024} KB" if str(e.get("size") or "").isdigit() else ""
            lines.append(f"- {e['name']}（{kind}{size}）")
        return "\n".join(lines)

    async def read_attachment(
        self,
        file_name: str = "",
        part: int = 1,
        __files__: Optional[list] = None,
        __user__: Optional[dict] = None,
        __event_emitter__: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> str:
        """
        讀取附件內容並轉成 Markdown。支援 Word（docx/doc/rtf）、Excel（xlsx/xls）、PowerPoint（pptx/ppt）、
        PDF、OpenDocument（odt/ods/odp）、CSV、HTML、EML 郵件，以及 SQL、log、程式碼等文字檔。
        內容太長時會分段，回傳結果會註明「第 X/Y 段」，需要後面的內容就用 part 讀下一段。
        :param file_name: 附件檔名，只有一個附件時可以留空
        :param part: 要讀第幾段，從 1 開始
        """
        try:
            entry = self._pick(__files__, file_name)
            await self._status(__event_emitter__, f"正在讀取 {entry['name']}")
            md = await self._markdown(entry, __user__)
            parts = _split_parts(md, self.valves.MAX_CHARS)
            part = max(1, min(part, len(parts)))
            await self._status(__event_emitter__, f"已讀取 {entry['name']}", done=True)
            header = f"# 附件：{entry['name']}（第 {part}/{len(parts)} 段）\n\n"
            footer = (
                f"\n\n> 還有後續內容，請用 read_attachment(file_name=\"{entry['name']}\", part={part + 1}) 繼續讀取。"
                if part < len(parts) else "\n\n> 已讀到最後一段。"
            )
            return header + parts[part - 1] + footer
        except Exception as e:
            await self._status(__event_emitter__, "讀取附件失敗", done=True)
            return f"讀取附件失敗：{e}"

    async def read_spreadsheet(
        self,
        file_name: str = "",
        sheet_name: str = "",
        start_row: int = 1,
        max_rows: int = 100,
        __files__: Optional[list] = None,
        __user__: Optional[dict] = None,
    ) -> str:
        """
        讀取試算表（xlsx、xls、ods、csv、tsv）指定工作表的指定範圍，適合資料很多、需要分批讀取的情況。
        回傳結果一定包含標題列（第 1 列）。
        :param file_name: 附件檔名，只有一個附件時可以留空
        :param sheet_name: 工作表名稱，留空表示第一個工作表
        :param start_row: 從第幾筆資料開始（1 表示標題列下的第一筆）
        :param max_rows: 最多讀幾筆
        """
        try:
            entry = self._pick(__files__, file_name)
            ext = os.path.splitext(entry["name"])[1].lower()
            if ext not in SHEET_EXT:
                return f"{entry['name']} 不是試算表，請改用 read_attachment。"
            path = await self._local_path(entry, __user__)
            sheets = await asyncio.to_thread(_load_sheets, path, ext)
            if not sheets:
                return "試算表中沒有工作表。"
            name = sheet_name or next(iter(sheets))
            if name not in sheets:
                return f"找不到工作表「{name}」。可用的工作表：" + "、".join(sheets)
            rows = sheets[name]
            if not rows:
                return f"工作表「{name}」是空的。"
            max_rows = max(1, min(max_rows, self.valves.MAX_ROWS))
            start = max(1, start_row)
            data = rows[start: start + max_rows]
            end = start + len(data) - 1
            total = len(rows) - 1
            md = _md_table([rows[0]] + data)
            more = (
                f"\n\n> 還有資料，請用 start_row={end + 1} 繼續讀取。" if end < total else "\n\n> 已讀到最後一筆。"
            )
            return f"# {entry['name']}／工作表：{name}（第 {start}～{end} 筆，共 {total} 筆）\n\n{md}{more}"
        except Exception as e:
            return f"讀取試算表失敗：{e}"

    async def search_attachment(
        self,
        keyword: str,
        file_name: str = "",
        max_results: int = 20,
        __files__: Optional[list] = None,
        __user__: Optional[dict] = None,
    ) -> str:
        """
        在附件中搜尋關鍵字，回傳包含關鍵字的段落與所在位置（頁、投影片、工作表）。
        文件很長、只需要找特定資訊時使用（例如找某個欄位名稱、錯誤代碼、條款）。
        :param keyword: 要搜尋的關鍵字（不分大小寫）
        :param file_name: 附件檔名，只有一個附件時可以留空
        :param max_results: 最多回傳幾筆結果
        """
        try:
            entry = self._pick(__files__, file_name)
            md = await self._markdown(entry, __user__)
            lines = md.splitlines()
            section, hits = "", []
            kw = keyword.lower()
            for i, line in enumerate(lines):
                if line.startswith("## "):
                    section = line[3:].strip()
                if kw in line.lower():
                    ctx = [l for l in lines[max(0, i - 1): i + 2] if l.strip()]
                    hits.append(f"- **{section or '內文'}**（第 {i + 1} 行）：\n  " + "\n  ".join(ctx))
                    if len(hits) >= max_results:
                        break
            if not hits:
                return f"在 {entry['name']} 中找不到「{keyword}」。"
            return f"在 {entry['name']} 中找到 {len(hits)} 筆「{keyword}」：\n\n" + "\n".join(hits)
        except Exception as e:
            return f"搜尋附件失敗：{e}"
