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
| Excel | xlsx、xlsm、xls | openpyxl；.xls 用 xlrd，沒有 xlrd 時改用 LibreOffice 轉檔 |
| PowerPoint | pptx、pptm | python-pptx |
| PDF | pdf | pdfplumber：有框線的表格轉成 Markdown 表格，其餘文字依版面由上到下排列；沒有 pdfplumber 時改用 pypdf 只擷取文字。掃描檔沒有文字層，會提示需要 OCR |
| OpenDocument | odt、ods、odp | Python 內建（zipfile + xml），不需要另外安裝 |
| 舊版格式 | doc、rtf、wps、ppt、pps | 需要 LibreOffice，先轉成 docx / pptx 再讀 |
| 其他 | csv、tsv、html、eml、zip（只列檔名）、txt、sql、log、json、xml、ktr、kjb、程式碼 | 內建 |

- 文字檔與 CSV 會自動判斷 UTF-8、Big5（cp950）、GB18030 編碼
- 試算表會依儲存格格式保留前導 0（例如工號 `01234`），日期轉成 `YYYY-MM-DD`

### 安裝

1. Open WebUI 管理員進入 **工作區 → 工具 → 新增工具**，貼上 `office_file_reader.py` 的全部內容後儲存
   - 檔案開頭的 `requirements:` 只列 Open WebUI 本身已內建的套件（python-docx、openpyxl、python-pptx、pypdf），儲存工具時不需要連外網
   - 選用套件（沒有也能用，只是少了部分功能）：

     | 套件 | 沒有時的影響 | Open WebUI 是否內建 |
     |---|---|---|
     | `pdfplumber` | PDF 的表格不會轉成 Markdown 表格，只擷取文字 | 否 |
     | `xlrd` | .xls 改用 LibreOffice 轉檔；兩者都沒有時，請使用者另存為 .xlsx | 新版有 |
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

---

## kettle_reader.py — Kettle Reader

解析 Kettle 的 .ktr（轉換）與 .kjb（作業），整理成流程摘要，存進**這個對話專屬的記憶**，搭配 `skills/read-kettle/SKILL.md` 使用。只用 Python 內建模組，不需要安裝任何套件。

### 提供的工具

| 工具 | 用途 |
|---|---|
| `analyze_kettle` | 解析 .ktr / .kjb：命名參數、資料庫連線、使用的變數、步驟與資料流向（作業則是執行順序與成功/失敗條件）、錯誤處理、停用的連線、mermaid 流程圖。結果自動存入記憶；同一個檔案內容沒變時直接從記憶取出 |
| `read_chat_memory` | 讀取這個對話的記憶 |
| `save_chat_memory` | 把整理好的說明存入記憶 |
| `delete_chat_memory` | 刪除記憶，`全部` 會清空這個對話的記憶 |

### 對話記憶的運作方式

- 存在 Open WebUI 資料夾下的 `chat_memory/<使用者ID>/<對話ID>.json`，每個對話一個檔案，其他對話與其他使用者都讀不到
- 用檔案內容的雜湊值判斷檔案有沒有改過：同一份檔案再問不會重新解析，上傳修改過的版本才會重新解析
- 資料庫密碼、寄信密碼等欄位在摘要中會顯示為「（已隱藏）」，不會存進記憶
- 暫時對話沒有對話 ID，無法保存記憶
- 刪除對話時，記憶檔不會自動刪除，可以先用 `delete_chat_memory("全部")` 清除，或由管理員定期清理 `chat_memory` 資料夾

### 安裝

1. **工作區 → 工具 → 新增工具**，貼上 `kettle_reader.py` 的全部內容後儲存
2. **工作區 → 模型**，勾選 **Kettle Reader** 工具，Function Calling 設為 **Native**
3. 在 **技能** 中加入 `read-kettle`

### 可調整的設定（Valves）

| 設定 | 預設 | 說明 |
|---|---|---|
| `MEMORY_DIR` | 空白（Open WebUI 資料夾下的 `chat_memory`） | 記憶存放位置 |
| `MAX_CHARS` | 12000 | 每次回傳的最大字數 |
| `MAX_ENTRY_CHARS` | 60000 | 每筆記憶最多保存的字數 |
| `MAX_ENTRIES` | 40 | 每個對話最多保存幾筆記憶 |
