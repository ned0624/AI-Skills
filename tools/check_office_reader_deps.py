"""
檢查 Office File Reader 需要的套件是否都已安裝。
請在 Open WebUI 執行的同一個 Python 環境中執行：python3 check_office_reader_deps.py
"""

import importlib
import importlib.metadata
import shutil
import sys

# pip 套件名稱 → import 名稱
PACKAGES = {
    "python-docx": "docx",
    "openpyxl": "openpyxl",
    "python-pptx": "pptx",
    "pypdf": "pypdf",
    "pdfplumber": "pdfplumber",
    "odfpy": "odf",
    "xlrd": "xlrd",
    "pydantic": "pydantic",
}

missing = []
print(f"Python {sys.version.split()[0]}（{sys.executable}）\n")
for pkg, module in PACKAGES.items():
    try:
        importlib.import_module(module)
        print(f"✅ {pkg} {importlib.metadata.version(pkg)}")
    except Exception as e:
        missing.append(pkg)
        print(f"❌ {pkg} 未安裝或無法載入（{type(e).__name__}: {e}）")

soffice = shutil.which("soffice") or shutil.which("libreoffice")
if soffice:
    print(f"✅ LibreOffice（{soffice}）")
else:
    print("⚠️ LibreOffice 未安裝：只影響 .doc / .ppt / .rtf 舊版格式，其他格式不受影響")

if missing:
    print("\n缺少的套件請執行：\npip install " + " ".join(missing))
else:
    print("\n必要套件都已安裝。")
