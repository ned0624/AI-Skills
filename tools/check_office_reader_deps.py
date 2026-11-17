"""
檢查 Office File Reader 需要的套件是否都已安裝。
請在 Open WebUI 執行的同一個 Python 環境中執行：python3 check_office_reader_deps.py
"""

import importlib
import importlib.metadata
import shutil
import sys

# pip 套件名稱 → import 名稱
REQUIRED = {
    "python-docx": "docx",
    "openpyxl": "openpyxl",
    "python-pptx": "pptx",
    "pypdf": "pypdf",
    "pydantic": "pydantic",
}
# 選用套件：沒有也能用，只是少了部分功能
OPTIONAL = {
    "pdfplumber": ("pdfplumber", "PDF 表格不會轉成 Markdown 表格，只擷取文字"),
    "xlrd": ("xlrd", ".xls 會改用 LibreOffice 轉檔"),
}

missing = []
print(f"Python {sys.version.split()[0]}（{sys.executable}）\n")
print("必要套件：")
for pkg, module in REQUIRED.items():
    try:
        importlib.import_module(module)
        print(f"✅ {pkg} {importlib.metadata.version(pkg)}")
    except Exception as e:
        missing.append(pkg)
        print(f"❌ {pkg} 未安裝或無法載入（{type(e).__name__}: {e}）")

print("\n選用套件：")
for pkg, (module, effect) in OPTIONAL.items():
    try:
        importlib.import_module(module)
        print(f"✅ {pkg} {importlib.metadata.version(pkg)}")
    except Exception:
        print(f"⚠️ {pkg} 未安裝：{effect}")

soffice = shutil.which("soffice") or shutil.which("libreoffice")
if soffice:
    print(f"✅ LibreOffice（{soffice}）")
else:
    print("⚠️ LibreOffice 未安裝：無法讀取 .doc / .ppt / .rtf；沒有 xlrd 時也無法讀取 .xls")

if missing:
    print("\n缺少必要套件，請執行：\npip install " + " ".join(missing))
else:
    print("\n必要套件都已安裝，工具可以使用。")
