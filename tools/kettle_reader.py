"""
title: Kettle Reader
description: 解析使用者上傳的 Kettle（Pentaho Data Integration）轉換檔 .ktr 與作業檔 .kjb，整理成流程摘要，並存進「這個對話專屬」的記憶，之後詢問不用重新解析
version: 1.0.0
license: MIT
"""

import hashlib
import inspect
import json
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Awaitable, Callable, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 步驟與作業項目類型的中文說明（只列常見的，其他直接顯示原始類型）
# ---------------------------------------------------------------------------

STEP_TYPES = {
    "TableInput": "表輸入", "TableOutput": "表輸出", "InsertUpdate": "插入/更新", "Update": "更新",
    "Delete": "刪除", "ExecSQL": "執行 SQL 腳本", "DBLookup": "資料庫查詢", "DBJoin": "資料庫連接",
    "StreamLookup": "串流查詢", "SelectValues": "選擇/改名值", "FilterRows": "過濾記錄",
    "SwitchCase": "Switch/Case", "Calculator": "計算機", "ScriptValueMod": "JavaScript 程式碼",
    "UserDefinedJavaClass": "Java 類別", "ValueMapper": "值映射", "StringOperations": "字串操作",
    "ReplaceString": "字串取代", "Constant": "增加常數", "SortRows": "排序", "Unique": "去除重複（需先排序）",
    "UniqueRowsByHashSet": "去除重複（HashSet）", "GroupBy": "分組", "MemoryGroupBy": "記憶體分組",
    "MergeRows": "合併記錄（新舊比對）", "SynchronizeAfterMerge": "合併後同步", "MergeJoin": "合併連接",
    "JoinRows": "記錄關聯（笛卡兒積）", "TextFileInput": "文字檔輸入", "CsvInput": "CSV 檔輸入",
    "TextFileOutput": "文字檔輸出", "ExcelInput": "Excel 輸入", "ExcelOutput": "Excel 輸出",
    "TypeExitExcelWriterStep": "Excel 寫入", "GetVariable": "取得變數", "SetVariable": "設定變數",
    "RowGenerator": "產生記錄", "SystemInfo": "取得系統資訊", "Dummy": "空操作",
    "Abort": "中止", "WriteToLog": "寫日誌", "BlockUntilStepsFinish": "阻塞直到步驟完成",
    "TransExecutor": "轉換執行器", "JobExecutor": "作業執行器", "OraBulkLoader": "Oracle 批量載入",
    "Mail": "寄信", "HTTP": "HTTP 用戶端", "Rest": "REST 用戶端", "JsonInput": "JSON 輸入",
    "JsonOutput": "JSON 輸出", "GetXMLData": "XML 輸入", "SequenceGenerator": "增加序列",
    "AddSequence": "增加序列", "Normaliser": "列轉行", "Denormaliser": "行轉列", "IfNull": "替換 NULL 值",
}
JOB_ENTRY_TYPES = {
    "SPECIAL": "開始/空操作", "TRANS": "執行轉換", "JOB": "執行作業", "SQL": "執行 SQL",
    "MAIL": "寄信", "EVAL": "JavaScript 判斷", "SIMPLE_EVAL": "條件判斷", "SET_VARIABLES": "設定變數",
    "SUCCESS": "成功結束", "ABORT": "中止作業", "WRITE_TO_LOG": "寫日誌", "CHECK_DB_CONNECTIONS": "檢查資料庫連線",
    "FILE_EXISTS": "檢查檔案是否存在", "DELETE_FILE": "刪除檔案", "DELETE_FILES": "刪除多個檔案",
    "COPY_FILES": "複製檔案", "MOVE_FILES": "移動檔案", "SHELL": "執行 Shell", "FTP": "FTP 下載",
    "FTP_PUT": "FTP 上傳", "SFTP": "SFTP 下載", "WAIT_FOR": "等待", "EVAL_TABLE_CONTENT": "評估表中記錄數",
    "TABLE_EXISTS": "檢查表是否存在", "COLUMNS_EXIST": "檢查欄位是否存在", "PING": "Ping",
}

# 解析設定時略過的欄位（畫面位置、預設值等雜訊）
NOISE_TAGS = {
    "name", "type", "description", "distribute", "custom_distribution", "copies", "partitioning",
    "attributes", "cluster_schema", "remotesteps", "GUI", "xloc", "yloc", "draw", "connection",
    "parallel", "nr", "start", "dummy", "attributes_kjc", "log_date", "log_size_limit_in_lines",
}
CODE_TAGS = {"sql", "script", "jsScript_script", "query", "code", "definition", "condition"}
SECRET_RE = re.compile(r"password|passwd|secret|token|private_?key", re.I)
VAR_RE = re.compile(r"\$\{([^}]+)\}|%%([^%]+)%%")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


# ---------------------------------------------------------------------------
# XML 小工具
# ---------------------------------------------------------------------------

def _t(el, path: str) -> str:
    node = el.find(path) if el is not None else None
    return (node.text or "").strip() if node is not None and node.text else ""


def _is_leaf(el) -> bool:
    return len(el) == 0


def _clean_value(tag: str, value: str) -> str:
    if SECRET_RE.search(tag) and value:
        return "（已隱藏）"
    return value


def _md_escape(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _settings_md(el, noise: set, depth: int = 0) -> list:
    """把步驟或作業項目的設定整理成條列，清單型設定轉成表格。"""
    lines = []
    groups = {}
    for child in el:
        if child.tag in noise:
            continue
        groups.setdefault(child.tag, []).append(child)

    for tag, nodes in groups.items():
        first = nodes[0]
        if all(_is_leaf(n) for n in nodes):
            for n in nodes:
                value = _clean_value(tag, (n.text or "").strip())
                if value in ("", "N", "0", "-1"):
                    continue
                if tag in CODE_TAGS or ("\n" in value and len(value) > 80):
                    lang = "sql" if tag in ("sql", "query") else ("javascript" if "script" in tag.lower() else "")
                    snippet = value if len(value) <= 4000 else value[:4000] + "\n…（以下省略）"
                    lines.append(f"- {tag}：\n```{lang}\n{snippet}\n```")
                else:
                    lines.append(f"- {tag}：{value[:300]}")
            continue

        # 有子元素：重複的同名子元素（例如 field）整理成表格
        rows = []
        for n in nodes:
            subs = {}
            for c in n:
                subs.setdefault(c.tag, []).append(c)
            repeated = [k for k, v in subs.items() if len(v) > 1 or not _is_leaf(v[0])]
            if repeated and depth < 2:
                for k in repeated:
                    for item in subs[k]:
                        if _is_leaf(item):
                            continue
                        row = {"項目": k} if len(repeated) > 1 else {}  # 例如查詢的 key 與 value 分開標示
                        for c in item:
                            if _is_leaf(c):
                                val = _clean_value(c.tag, (c.text or "").strip())
                                if val not in ("", "N", "-1", "-2"):
                                    row[c.tag] = val
                        if len(row) > (1 if len(repeated) > 1 else 0):
                            rows.append(row)
            leaf_pairs = [
                f"{c.tag}={_clean_value(c.tag, (c.text or '').strip())}"
                for c in n if _is_leaf(c) and (c.text or "").strip() not in ("", "N", "0", "-1")
            ]
            if leaf_pairs:
                lines.append(f"- {tag}：" + "，".join(leaf_pairs)[:400])
        if rows:
            cols = []
            for r in rows:
                for k in r:
                    if k not in cols:
                        cols.append(k)
            cols = cols[:8]
            shown = rows[:50]
            table = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
            table += ["| " + " | ".join(_md_escape(r.get(c, ""))[:80] for c in cols) + " |" for r in shown]
            more = f"\n（共 {len(rows)} 筆，只列前 50 筆）" if len(rows) > 50 else ""
            lines.append(f"- {tag}（{len(rows)} 筆）：\n\n" + "\n".join(table) + more)
    return lines


def _connections_md(root) -> list:
    out = []
    for c in root.findall("connection"):
        parts = [f"類型 {_t(c, 'type')}"]
        server, db, port, user = _t(c, "server"), _t(c, "database"), _t(c, "port"), _t(c, "username")
        if server:
            parts.append(f"主機 {server}" + (f":{port}" if port else ""))
        if db:
            parts.append(f"資料庫 {db}")
        if user:
            parts.append(f"帳號 {user}")
        out.append(f"- **{_t(c, 'name')}**：" + "，".join(parts))
    return out


def _parameters_md(root) -> list:
    params = root.findall("info/parameters/parameter") or root.findall("parameters/parameter")
    out = []
    for p in params:
        default = _t(p, "default_value")
        desc = _t(p, "description")
        out.append(f"- `{_t(p, 'name')}`" + (f"（預設 {default}）" if default else "") + (f"：{desc}" if desc else ""))
    return out


def _variables(raw: str) -> list:
    names = []
    for a, b in VAR_RE.findall(raw):
        n = a or b
        if n and n not in names and not n.startswith("Internal."):
            names.append(n)
    return names


def _flow_order(nodes: list, edges: list) -> list:
    """依連線排出執行順序（Kahn 拓樸排序），有迴圈時剩下的依原順序接在後面。"""
    incoming = {n: 0 for n in nodes}
    for a, b, _ in edges:
        if b in incoming:
            incoming[b] += 1
    linked = {a for a, _, _ in edges} | {b for _, b, _ in edges}
    # 沒有任何連線的步驟（例如連線被停用）放到最後
    queue = [n for n in nodes if incoming[n] == 0 and n in linked]
    order, seen = [], set()
    while queue:
        n = queue.pop(0)
        if n in seen:
            continue
        seen.add(n)
        order.append(n)
        for a, b, _ in edges:
            if a == n and b in incoming:
                incoming[b] -= 1
                if incoming[b] == 0:
                    queue.append(b)
    return order + [n for n in nodes if n not in seen and n in linked] + [n for n in nodes if n not in linked]


def _mermaid(edges: list) -> str:
    ids = {}

    def nid(name):
        if name not in ids:
            ids[name] = f"n{len(ids)}"
        return ids[name]

    lines = ["```mermaid", "flowchart TD"]
    for a, b, label in edges:
        a_label = a.replace('"', "'")
        b_label = b.replace('"', "'")
        arrow = f" -->|{label}| " if label else " --> "
        lines.append(f'    {nid(a)}["{a_label}"]{arrow}{nid(b)}["{b_label}"]')
    lines.append("```")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 解析 .ktr / .kjb
# ---------------------------------------------------------------------------

def analyze_kettle_xml(raw: str, filename: str) -> dict:
    """回傳 {"kind", "name", "overview", "details", "referenced_files"}。"""
    root = ET.fromstring(raw)
    if root.tag == "transformation":
        return _analyze_ktr(root, raw, filename)
    if root.tag == "job":
        return _analyze_kjb(root, raw, filename)
    raise RuntimeError(f"{filename} 不是 Kettle 轉換（.ktr）或作業（.kjb）檔")


def _common_header(kind: str, name: str, filename: str, root, raw: str) -> list:
    desc = _t(root, "info/description") or _t(root, "description")
    out = [f"# Kettle {kind}：{name}（檔案 {filename}）"]
    if desc:
        out.append(f"說明：{desc}")
    params = _parameters_md(root)
    if params:
        out.append("## 命名參數\n" + "\n".join(params))
    conns = _connections_md(root)
    if conns:
        out.append("## 資料庫連線\n" + "\n".join(conns))
    variables = _variables(raw)
    if variables:
        out.append("## 使用到的變數\n" + "、".join(f"`{v}`" for v in variables))
    return out


def _analyze_ktr(root, raw: str, filename: str) -> dict:
    name = _t(root, "info/name") or filename
    steps = root.findall("step")
    step_type = {_t(s, "name"): _t(s, "type") for s in steps}
    edges, disabled = [], []
    for h in root.findall("order/hop"):
        a, b = _t(h, "from"), _t(h, "to")
        if _t(h, "enabled") == "N":
            disabled.append(f"{a} → {b}")
        else:
            edges.append((a, b, ""))
    errors = []
    for e in root.findall("step_error_handling/error"):
        if _t(e, "is_enabled") == "Y":
            src, dst = _t(e, "source_step"), _t(e, "target_step")
            errors.append(f"{src} → {dst}")
            edges.append((src, dst, "錯誤資料"))

    overview = _common_header("轉換", name, filename, root, raw)
    order = _flow_order([_t(s, "name") for s in steps], edges)
    flow = []
    for i, n in enumerate(order, 1):
        t = step_type.get(n, "")
        nxt = [f"{b}" + (f"（{label}）" if label else "") for a, b, label in edges if a == n]
        flow.append(f"{i}. **{n}**（{STEP_TYPES.get(t, t)}）" + (" → " + "、".join(nxt) if nxt else "　【結束】"))
    overview.append(
        "## 步驟與資料流向\n"
        "> 注意：轉換中的所有步驟是同時啟動、平行執行的，下面的順序代表資料流向，不是執行先後。\n\n"
        + "\n".join(flow)
    )
    if errors:
        overview.append("## 錯誤處理\n" + "\n".join(f"- {e}" for e in errors))
    if disabled:
        overview.append("## 已停用的連線\n" + "\n".join(f"- {d}" for d in disabled))
    if edges:
        overview.append("## 流程圖\n" + _mermaid(edges))

    details = [f"# {name} 各步驟設定"]
    for s in steps:
        n, t = _t(s, "name"), _t(s, "type")
        head = f"## {n}（{STEP_TYPES.get(t, t)}，{t}）"
        meta = []
        if _t(s, "connection"):
            meta.append(f"- 連線：{_t(s, 'connection')}")
        if _t(s, "copies") not in ("", "1"):
            meta.append(f"- 平行份數：{_t(s, 'copies')}")
        if _t(s, "description"):
            meta.append(f"- 說明：{_t(s, 'description')}")
        details.append(head + "\n" + "\n".join(meta + _settings_md(s, NOISE_TAGS)))
    return {"kind": "轉換", "name": name, "overview": "\n\n".join(overview),
            "details": "\n\n".join(details), "referenced_files": []}


def _analyze_kjb(root, raw: str, filename: str) -> dict:
    name = _t(root, "name") or filename
    entries = root.findall("entries/entry")
    entry_type = {_t(e, "name"): _t(e, "type") for e in entries}
    edges, disabled = [], []
    for h in root.findall("hops/hop"):
        a, b = _t(h, "from"), _t(h, "to")
        if _t(h, "unconditional") == "Y":
            label = "無條件"
        elif _t(h, "evaluation") == "N":
            label = "失敗時"
        else:
            label = "成功時"
        if _t(h, "enabled") == "N":
            disabled.append(f"{a} →（{label}）{b}")
        else:
            edges.append((a, b, label))

    referenced = []
    for e in entries:
        fn = _t(e, "filename") or _t(e, "transname") or _t(e, "jobname")
        if fn and _t(e, "type") in ("TRANS", "JOB"):
            referenced.append(os.path.basename(fn.replace("\\", "/")))

    overview = _common_header("作業", name, filename, root, raw)
    names = [_t(e, "name") for e in entries]
    starts = [n for n in names if entry_type.get(n) == "SPECIAL" and n.upper().startswith("START")]
    order = _flow_order(starts + [n for n in names if n not in starts], edges)
    flow = []
    for i, n in enumerate(order, 1):
        t = entry_type.get(n, "")
        nxt = [f"{b}（{label}）" for a, b, label in edges if a == n]
        flow.append(f"{i}. **{n}**（{JOB_ENTRY_TYPES.get(t, t)}）" + (" → " + "、".join(nxt) if nxt else "　【結束】"))
    overview.append("## 執行順序\n> 作業中的項目依連線依序執行，連線條件決定下一步。\n\n" + "\n".join(flow))
    if referenced:
        overview.append("## 呼叫的轉換 / 作業檔\n" + "\n".join(f"- {r}" for r in referenced))
    if disabled:
        overview.append("## 已停用的連線\n" + "\n".join(f"- {d}" for d in disabled))
    if edges:
        overview.append("## 流程圖\n" + _mermaid(edges))

    details = [f"# {name} 各項目設定"]
    for e in entries:
        n, t = _t(e, "name"), _t(e, "type")
        meta = [f"- 連線：{_t(e, 'connection')}"] if _t(e, "connection") else []
        details.append(f"## {n}（{JOB_ENTRY_TYPES.get(t, t)}，{t}）\n" + "\n".join(meta + _settings_md(e, NOISE_TAGS)))
    return {"kind": "作業", "name": name, "overview": "\n\n".join(overview),
            "details": "\n\n".join(details), "referenced_files": referenced}


# ---------------------------------------------------------------------------
# 對話專屬記憶：每個使用者、每個對話一個 JSON 檔，其他對話讀不到
# ---------------------------------------------------------------------------

class ChatMemory:
    def __init__(self, base_dir: str, user_id: str, chat_id: str):
        if not chat_id or not SAFE_ID_RE.match(chat_id):
            raise RuntimeError("這是暫時對話或無法識別的對話，無法保存記憶。請在一般對話中使用")
        if not user_id or not SAFE_ID_RE.match(user_id):
            raise RuntimeError("無法識別使用者，無法保存記憶")
        self.path = os.path.join(base_dir, user_id, chat_id + ".json")

    def load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def save(self, data: dict):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)  # 先寫暫存檔再換名，避免寫到一半損壞

    def put(self, title: str, content: str, **meta):
        data = self.load()
        data[title] = {"content": content, "updated": datetime.now().strftime("%Y-%m-%d %H:%M"), **meta}
        self.save(data)


# ---------------------------------------------------------------------------
# Open WebUI 工具
# ---------------------------------------------------------------------------

class Tools:
    class Valves(BaseModel):
        MEMORY_DIR: str = Field(default="", description="對話記憶存放的資料夾，留空表示 Open WebUI 資料夾下的 chat_memory")
        MAX_CHARS: int = Field(default=12000, description="每次回傳的最大字數，依模型 context 長度調整")
        MAX_ENTRY_CHARS: int = Field(default=60000, description="每筆記憶最多保存的字數")
        MAX_ENTRIES: int = Field(default=40, description="每個對話最多保存幾筆記憶")

    def __init__(self):
        self.valves = self.Valves()

    # ---- 記憶 -------------------------------------------------------------

    def _memory_dir(self) -> str:
        if self.valves.MEMORY_DIR:
            return self.valves.MEMORY_DIR
        try:
            from open_webui.env import DATA_DIR
            return os.path.join(str(DATA_DIR), "chat_memory")
        except ImportError:
            return os.path.join(os.getenv("DATA_DIR", "data"), "chat_memory")

    def _memory(self, user: Optional[dict], chat_id: Optional[str]) -> ChatMemory:
        return ChatMemory(self._memory_dir(), (user or {}).get("id", ""), chat_id or "")

    def _put(self, mem: ChatMemory, title: str, content: str, **meta):
        data = mem.load()
        if title not in data and len(data) >= self.valves.MAX_ENTRIES:
            raise RuntimeError(f"這個對話的記憶已達 {self.valves.MAX_ENTRIES} 筆上限，請先用 delete_chat_memory 刪除不需要的")
        if len(content) > self.valves.MAX_ENTRY_CHARS:
            content = content[: self.valves.MAX_ENTRY_CHARS] + "\n…（超過保存上限，以下省略）"
        mem.put(title, content, **meta)

    # ---- 附件（與 Office File Reader 相同的安全做法） --------------------------

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
            })
        return [
            e for e in out
            if e["type"] == "file" and e["id"] and not str(e["id"]).startswith(("http://", "https://", "data:"))
        ]

    @staticmethod
    async def _maybe_await(value):
        return await value if inspect.isawaitable(value) else value

    async def _can_read(self, rec, user: Optional[dict]) -> bool:
        if not user:
            return False
        if rec.user_id == user.get("id") or user.get("role") == "admin":
            return True
        try:
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
            path = entry.get("path")
            if path and os.path.exists(path):
                return path
            raise RuntimeError("找不到附件的檔案位置")
        # __files__ 來自前端請求，不可信任其中的 path，一律從資料庫查檔案並檢查權限
        rec = await self._maybe_await(Files.get_file_by_id(entry["id"]))
        if rec is None or not rec.path:
            raise RuntimeError("附件已不存在，請使用者重新上傳")
        if not await self._can_read(rec, user):
            raise PermissionError("沒有權限讀取這個附件")
        return await self._maybe_await(Storage.get_file(rec.path))

    def _kettle_entries(self, files: Optional[list], file_name: str) -> list:
        entries = [e for e in self._entries(files) if os.path.splitext(e["name"])[1].lower() in (".ktr", ".kjb")]
        if not entries:
            raise RuntimeError("這則對話沒有 .ktr 或 .kjb 附件")
        if not file_name:
            return entries
        for test in (
            lambda e: e["name"] == file_name,
            lambda e: e["name"].lower() == file_name.lower(),
            lambda e: file_name.lower() in e["name"].lower(),
        ):
            hits = [e for e in entries if test(e)]
            if hits:
                return hits
        raise RuntimeError(f"找不到「{file_name}」。目前的 Kettle 附件：" + "、".join(e["name"] for e in entries))

    @staticmethod
    async def _status(emitter, text: str, done: bool = False):
        if emitter:
            await emitter({"type": "status", "data": {"description": text, "done": done}})

    def _fit(self, text: str, hint: str) -> str:
        if len(text) <= self.valves.MAX_CHARS:
            return text
        return text[: self.valves.MAX_CHARS] + f"\n\n> 內容太長，只顯示前段。{hint}"

    # ---- 提供給模型的工具 -----------------------------------------------------

    async def analyze_kettle(
        self,
        file_name: str = "",
        refresh: bool = False,
        __files__: Optional[list] = None,
        __user__: Optional[dict] = None,
        __chat_id__: Optional[str] = None,
        __event_emitter__: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> str:
        """
        解析 Kettle 轉換檔（.ktr）或作業檔（.kjb），回傳流程摘要：參數、資料庫連線、使用的變數、
        步驟與資料流向（或作業執行順序與成功/失敗條件）、流程圖，並自動存進這個對話的記憶。
        同一個檔案已經分析過且內容沒變時，直接從記憶取出，不會重新解析。
        :param file_name: Kettle 附件檔名，留空表示分析所有 .ktr / .kjb 附件
        :param refresh: 設為 true 時強制重新解析
        """
        try:
            entries = self._kettle_entries(__files__, file_name)
            try:
                mem = self._memory(__user__, __chat_id__)
                stored = mem.load()
            except RuntimeError as e:
                mem, stored = None, {}
                memory_note = f"\n\n> ⚠️ {e}"
            else:
                memory_note = ""

            results, referenced = [], []
            for entry in entries:
                path = await self._local_path(entry, __user__)
                with open(path, "rb") as f:
                    raw_bytes = f.read()
                digest = hashlib.sha256(raw_bytes).hexdigest()
                title = f"{entry['name']} 流程"
                cached = stored.get(title)
                if cached and cached.get("sha256") == digest and not refresh:
                    results.append(cached["content"] + "\n\n> （從這個對話的記憶取出，檔案內容沒有變更，未重新解析）")
                    referenced += cached.get("referenced_files", [])
                    continue

                await self._status(__event_emitter__, f"正在解析 {entry['name']}")
                info = analyze_kettle_xml(raw_bytes.decode("utf-8", errors="replace"), entry["name"])
                referenced += info["referenced_files"]
                if mem:
                    self._put(mem, title, info["overview"], sha256=digest, source=entry["name"],
                              referenced_files=info["referenced_files"])
                    self._put(mem, f"{entry['name']} 步驟設定", info["details"], sha256=digest, source=entry["name"])
                results.append(info["overview"])

            await self._status(__event_emitter__, "Kettle 檔案解析完成", done=True)
            uploaded = {e["name"] for e in self._entries(__files__)}
            missing = sorted({r for r in referenced if r not in uploaded})
            tail = []
            if missing:
                tail.append("> 作業有呼叫以下檔案，但使用者沒有上傳，需要時請使用者補上傳：" + "、".join(missing))
            if mem:
                tail.append("> 各步驟的詳細設定（SQL、欄位對應等）已存入記憶，需要時用 "
                            "read_chat_memory(title=\"檔名 步驟設定\") 讀取。")
            body = "\n\n---\n\n".join(results)
            return self._fit(body, "完整內容已存入記憶，可用 read_chat_memory 分批讀取。") + \
                ("\n\n" + "\n".join(tail) if tail else "") + memory_note
        except Exception as e:
            await self._status(__event_emitter__, "解析 Kettle 檔案失敗", done=True)
            return f"解析 Kettle 檔案失敗：{e}"

    async def read_chat_memory(
        self,
        title: str = "",
        part: int = 1,
        __user__: Optional[dict] = None,
        __chat_id__: Optional[str] = None,
    ) -> str:
        """
        讀取這個對話已保存的記憶（例如之前解析過的 Kettle 流程摘要、步驟設定、整理過的結論）。
        回答關於先前檔案或流程的問題前，先呼叫這個工具，不需要重新解析或重新讀檔。
        :param title: 記憶標題，留空表示列出所有記憶（內容不多時會一併回傳全文）
        :param part: 內容很長時要讀第幾段，從 1 開始
        """
        try:
            data = self._memory(__user__, __chat_id__).load()
            if not data:
                return "這個對話目前沒有保存任何記憶。"
            if not title:
                total = sum(len(v.get("content", "")) for v in data.values())
                listing = "\n".join(
                    f"- {k}（{len(v.get('content', ''))} 字，更新於 {v.get('updated', '')}）" for k, v in data.items()
                )
                if total <= self.valves.MAX_CHARS:
                    full = "\n\n---\n\n".join(f"### 記憶：{k}\n\n{v['content']}" for k, v in data.items())
                    return f"這個對話的記憶：\n{listing}\n\n{full}"
                return f"這個對話的記憶（內容較多，請指定 title 讀取）：\n{listing}"
            key = title if title in data else next((k for k in data if title.lower() in k.lower()), None)
            if key is None:
                return f"找不到標題含「{title}」的記憶。目前有：" + "、".join(data)
            content = data[key]["content"]
            size = self.valves.MAX_CHARS
            parts = max(1, -(-len(content) // size))
            part = max(1, min(part, parts))
            chunk = content[(part - 1) * size: part * size]
            more = f"\n\n> 還有後續內容，請用 part={part + 1} 繼續讀取。" if part < parts else ""
            return f"### 記憶：{key}（第 {part}/{parts} 段）\n\n{chunk}{more}"
        except Exception as e:
            return f"讀取記憶失敗：{e}"

    async def save_chat_memory(
        self,
        title: str,
        content: str,
        __user__: Optional[dict] = None,
        __chat_id__: Optional[str] = None,
    ) -> str:
        """
        把整理好的內容存進這個對話的記憶（只有這個對話看得到），例如整體流程說明、問題分析結論、
        使用者確認過的事項。同標題會覆蓋舊內容。
        :param title: 記憶標題，例如「整體流程說明」
        :param content: 要保存的內容（Markdown）
        """
        try:
            self._put(self._memory(__user__, __chat_id__), title.strip()[:100] or "未命名", content)
            return f"已存入這個對話的記憶：{title}"
        except Exception as e:
            return f"保存記憶失敗：{e}"

    async def delete_chat_memory(
        self,
        title: str,
        __user__: Optional[dict] = None,
        __chat_id__: Optional[str] = None,
    ) -> str:
        """
        刪除這個對話的一筆記憶。title 填「全部」會清空這個對話的所有記憶。
        :param title: 要刪除的記憶標題
        """
        try:
            mem = self._memory(__user__, __chat_id__)
            data = mem.load()
            if title == "全部":
                mem.save({})
                return f"已清空這個對話的 {len(data)} 筆記憶。"
            if title not in data:
                return f"找不到「{title}」。目前有：" + "、".join(data)
            del data[title]
            mem.save(data)
            return f"已刪除記憶：{title}"
        except Exception as e:
            return f"刪除記憶失敗：{e}"
