# Open WebUI 工具

## office_file_reader.py — Office File Reader

把使用者上傳的附件轉成 Markdown 給模型閱讀，搭配 `skills/read-office-files/SKILL.md` 使用。

### 提供的工具

| 工具 | 用途 |
|---|---|
| `list_attachments` | 列出這則對話的附件 |
| `read_attachment` | 把附件轉成 Markdown，太長會分段，用 `part` 讀下一段 |
| `read_spreadsheet` | 分批讀取試算表的指定工作表與範圍（每次附上標題列） |
| `search_attachment` | 在附件中搜尋關鍵字，回傳所在頁、投影片或工作表 |

### 支援格式

| 類型 | 副檔名 | 使用的套件 |
|---|---|---|
| Word | docx、docm | python-docx |
| Excel | xlsx、xlsm、xls | openpyxl、xlrd |
| PowerPoint | pptx、pptm | python-pptx |
| PDF | pdf | pdfplumber：有框線的表格轉成 Markdown 表格，其餘文字依版面由上到下排列；沒有 pdfplumber 時改用 pypdf 只擷取文字。掃描檔沒有文字層，會提示需要 OCR |
| OpenDocument | odt、ods、odp | odfpy |
| 舊版格式 | doc、rtf、wps、ppt、pps | 需要 LibreOffice，先轉成 docx / pptx 再讀 |
| 其他 | csv、tsv、html、eml、zip（只列檔名）、txt、sql、log、json、xml、ktr、kjb、程式碼 | 內建 |

- 文字檔與 CSV 會自動判斷 UTF-8、Big5（cp950）、GB18030 編碼
- 試算表會依儲存格格式保留前導 0（例如工號 `01234`），日期轉成 `YYYY-MM-DD`

### 安裝

1. Open WebUI 管理員進入 **工作區 → 工具 → 新增工具**，貼上 `office_file_reader.py` 的全部內容後儲存
   - 檔案開頭的 `requirements:` 會讓 Open WebUI 自動安裝需要的 Python 套件
   - 伺服器不能連外網時，請先在 Open WebUI 的環境中手動安裝：
     `pip install python-docx openpyxl python-pptx pypdf pdfplumber odfpy xlrd`
   - 確認套件是否都裝好：在 Open WebUI 的環境執行 `check_office_reader_deps.py`。Docker 安裝的話：
     ```
     docker cp check_office_reader_deps.py open-webui:/tmp/
     docker exec open-webui python3 /tmp/check_office_reader_deps.py
     ```
     缺少套件時，最後會列出要執行的 `pip install` 指令（Docker 就在前面加上 `docker exec open-webui`）
2. 要讀 .doc、.ppt、.rtf 舊版格式時，Open WebUI 伺服器（或容器）要安裝 LibreOffice，例如 Docker 映像中加入
   `apt-get install -y libreoffice-writer libreoffice-impress`
3. 到 **工作區 → 模型**，編輯要使用的模型：
   - 勾選 **Office File Reader** 工具
   - 進階參數的 **Function Calling** 設為 **Native**（Qwen 支援原生工具呼叫）
4. 在 **技能** 中加入 `read-office-files`、`read-attachments`、`ask-user` 三個 skill

### 可調整的設定（Valves）

在工具的設定（齒輪圖示）中調整：

| 設定 | 預設 | 說明 |
|---|---|---|
| `MAX_CHARS` | 12000 | `read_attachment` 每段的最大字數，模型 context 較小時調低 |
| `PREVIEW_ROWS` | 100 | `read_attachment` 每個工作表最多顯示幾筆 |
| `MAX_ROWS` | 200 | `read_spreadsheet` 每次最多回傳幾筆 |
| `SOFFICE_PATH` | `soffice` | LibreOffice 執行檔路徑 |

### 安全性

- 工具不信任前端送來的檔案路徑，一律用檔案 ID 從 Open WebUI 資料庫查詢檔案，並檢查使用者是否為檔案擁有者、管理員，或有共用讀取權限
- 不會解壓縮 zip，也不會執行附件中的任何內容
