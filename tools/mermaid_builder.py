"""
title: Mermaid Builder
description: 產生語法正確的 Mermaid 圖（流程圖、ER 圖、循序圖、甘特圖），以及檢查並修正模型寫錯的 Mermaid 語法。Open WebUI 會直接把 mermaid 程式碼區塊畫成圖
version: 1.0.0
license: MIT
"""

import re
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 共用
# ---------------------------------------------------------------------------

def _q(text: str) -> str:
    """節點或連線文字一律加雙引號；文字中的雙引號改成 Mermaid 的跳脫寫法。"""
    text = str(text).strip().replace('"', "#quot;")
    return f'"{text}"'


def _clean_plain(text: str) -> str:
    """循序圖、甘特圖中不能加引號的文字：把會破壞語法的符號換成全形。"""
    return (str(text).strip().replace(";", "；").replace("#", "＃").replace("%%", "％％"))


def _code_block(code: str, note: str = "") -> str:
    head = "以下是產生的 Mermaid 圖，請把整個程式碼區塊原封不動放進回覆（不要修改內容）：\n\n"
    return head + "```mermaid\n" + code.strip() + "\n```" + (f"\n\n{note}" if note else "")


def _lines(text: str) -> list:
    out = []
    for raw in str(text).replace("\r", "").split("\n"):
        line = raw.strip()
        if line and not line.startswith(("#", "//", "%%")):
            out.append(line)
    return out


# ---------------------------------------------------------------------------
# 流程圖
# ---------------------------------------------------------------------------

# 節點形狀標記：寫在節點文字外面，例如 {主管審核}、([開始])、[(資料庫)]
SHAPES = [
    ("([", "])", "stadium"), ("[(", ")]", "cylinder"), ("[[", "]]", "subroutine"),
    ("((", "))", "circle"), ("{{", "}}", "hexagon"), ("[/", "/]", "parallelogram"),
    ("{", "}", "rhombus"), ("(", ")", "round"), ("[", "]", "rect"),
]
SHAPE_SYNTAX = {
    "rect": ("[", "]"), "round": ("(", ")"), "stadium": ("([", "])"), "cylinder": ("[(", ")]"),
    "subroutine": ("[[", "]]"), "circle": ("((", "))"), "hexagon": ("{{", "}}"),
    "parallelogram": ("[/", "/]"), "rhombus": ("{", "}"),
}
TERMINAL_WORDS = {"開始", "結束", "完成", "起點", "終點", "start", "end", "begin", "finish", "done"}
ARROWS = [("-.->", "-.->"), ("..>", "-.->"), ("==>", "==>"), ("-->", "-->"), ("->", "-->"), ("→", "-->")]
ARROW_RE = re.compile(r"\s*(-\.->|\.\.>|==>|-->|->|→)\s*")


def _parse_node(token: str):
    token = token.strip()
    for start, end, shape in SHAPES:
        if token.startswith(start) and token.endswith(end) and len(token) > len(start) + len(end):
            return token[len(start):-len(end)].strip(), shape
    if token.lower() in TERMINAL_WORDS:
        return token, "stadium"
    if token.endswith(("?", "？")):
        return token, "rhombus"
    return token, None


def build_flowchart_code(steps: str, direction: str = "TD") -> str:
    direction = direction.upper() if direction.upper() in ("TD", "TB", "LR", "RL", "BT") else "TD"
    ids, shapes, body = {}, {}, []
    declared = set()
    indent = 1

    def node(token: str) -> str:
        label, shape = _parse_node(token)
        if label not in ids:
            ids[label] = f"n{len(ids) + 1}"
        if shape and label not in shapes:
            shapes[label] = shape
        return label

    def ref(label: str) -> str:
        nid = ids[label]
        if nid in declared:
            return nid
        declared.add(nid)
        open_, close = SHAPE_SYNTAX[shapes.get(label, "rect")]
        return f"{nid}{open_}{_q(label)}{close}"

    for line in _lines(steps):
        low = line.lower()
        if low.startswith("subgraph "):
            body.append("    " * indent + f"subgraph g{len(body)}[{_q(line[9:])}]")
            indent += 1
            continue
        if low == "end" and indent > 1:
            indent -= 1
            body.append("    " * indent + "end")
            continue

        parts = ARROW_RE.split(line)
        label_text = ""
        # 最後一段的「: 文字」或「：文字」是連線文字
        m = re.match(r"^(.*?)\s*(?:\s:\s|：|(?<!\w):(?!\w))\s*(.+)$", parts[-1]) if len(parts) > 1 else None
        if m:
            parts[-1], label_text = m.group(1), m.group(2)
        if len(parts) == 1:
            ref_label = node(parts[0])
            body.append("    " * indent + ref(ref_label))
            continue
        nodes = [node(p) for p in parts[0::2]]
        arrows = [dict(ARROWS)[a] for a in parts[1::2]]
        for i, arrow in enumerate(arrows):
            a, b = nodes[i], nodes[i + 1]
            text = label_text if i == len(arrows) - 1 else ""
            mid = f" {arrow}|{_q(text)}| " if text else f" {arrow} "
            body.append("    " * indent + ref(a) + mid + ref(b))
    while indent > 1:
        indent -= 1
        body.append("    " * indent + "end")
    return f"flowchart {direction}\n" + "\n".join(body)


# ---------------------------------------------------------------------------
# ER 圖（從 Oracle / 一般 SQL 的 DDL 解析）
# ---------------------------------------------------------------------------

def _strip_sql_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"--[^\n]*", " ", sql)


def _split_top(text: str, sep: str = ",") -> list:
    """依逗號切開，但不切括號或引號裡的逗號。"""
    parts, depth, cur, quote = [], 0, [], None
    for ch in text:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur).strip())
    return parts


def _ident(name: str) -> str:
    name = name.strip().strip('"`[]').upper()
    return re.sub(r"[^A-Z0-9_]", "_", name.split(".")[-1])


def _cols(text: str) -> list:
    return [_ident(c) for c in text.split(",") if c.strip()]


def parse_ddl(ddl: str) -> tuple:
    """回傳 (tables, relations)。tables: {表名: {"cols": [...], "comment": str}}。"""
    sql = _strip_sql_comments(ddl)
    tables, relations = {}, []

    def add_fk(child, cols, parent, pcols):
        relations.append((parent, child, cols, pcols))

    for m in re.finditer(r"create\s+(?:global\s+temporary\s+)?table\s+([\w.\"$#`]+)\s*\(", sql, re.I):
        name = _ident(m.group(1))
        start, depth, i = m.end(), 1, m.end()
        while i < len(sql) and depth:
            depth += {"(": 1, ")": -1}.get(sql[i], 0)
            i += 1
        body = sql[start:i - 1]
        cols, pk = [], set()
        for item in _split_top(body):
            low = item.lower()
            cm = re.match(r"(?:constraint\s+[\w\"$#]+\s+)?primary\s+key\s*\(([^)]*)\)", low)
            if cm:
                pk.update(_cols(cm.group(1)))
                continue
            fm = re.match(
                r"(?:constraint\s+[\w\"$#]+\s+)?foreign\s+key\s*\(([^)]*)\)\s*references\s+([\w.\"$#`]+)\s*(?:\(([^)]*)\))?",
                item, re.I)
            if fm:
                add_fk(name, _cols(fm.group(1)), _ident(fm.group(2)), _cols(fm.group(3) or ""))
                continue
            if re.match(r"(constraint|unique|check|index|key)\b", low):
                continue
            tm = re.match(r"([\w\"$#`]+)\s+([A-Za-z][\w ]*?(?:\s*\([^)]*\))?)(?=\s|$)(.*)$", item, re.S)
            if not tm:
                continue
            col, ctype, rest = _ident(tm.group(1)), tm.group(2).strip(), tm.group(3)
            ctype = re.sub(r"\s+", "_", re.sub(r"\s*\(\s*([^)]*?)\s*\)", lambda x: "_" + x.group(1).replace(",", "_").replace(" ", ""), ctype))
            ctype = re.sub(r"[^A-Za-z0-9_]", "", ctype.upper()) or "UNKNOWN"
            if re.search(r"\bprimary\s+key\b", rest, re.I):
                pk.add(col)
            rm = re.search(r"\breferences\s+([\w.\"$#`]+)\s*(?:\(([^)]*)\))?", rest, re.I)
            if rm:
                add_fk(name, [col], _ident(rm.group(1)), _cols(rm.group(2) or ""))
            cols.append({"name": col, "type": ctype, "pk": False, "fk": False, "comment": ""})
        for c in cols:
            c["pk"] = c["name"] in pk
        tables[name] = {"cols": cols, "comment": ""}

    for m in re.finditer(
        r"alter\s+table\s+([\w.\"$#`]+)\s+add\s+(?:constraint\s+[\w\"$#]+\s+)?(primary|foreign)\s+key\s*\(([^)]*)\)"
        r"(?:\s*references\s+([\w.\"$#`]+)\s*(?:\(([^)]*)\))?)?", sql, re.I):
        tname, kind, cols = _ident(m.group(1)), m.group(2).lower(), _cols(m.group(3))
        if kind == "primary" and tname in tables:
            for c in tables[tname]["cols"]:
                if c["name"] in cols:
                    c["pk"] = True
        elif kind == "foreign" and m.group(4):
            add_fk(tname, cols, _ident(m.group(4)), _cols(m.group(5) or ""))

    for m in re.finditer(r"comment\s+on\s+column\s+([\w.\"$#`]+)\s+is\s+'((?:[^']|'')*)'", sql, re.I):
        parts = [p.strip('"`').upper() for p in m.group(1).split(".")]
        if len(parts) >= 2 and _ident(parts[-2]) in tables:
            for c in tables[_ident(parts[-2])]["cols"]:
                if c["name"] == _ident(parts[-1]):
                    c["comment"] = m.group(2).replace("''", "'")
    for m in re.finditer(r"comment\s+on\s+table\s+([\w.\"$#`]+)\s+is\s+'((?:[^']|'')*)'", sql, re.I):
        t = _ident(m.group(1))
        if t in tables:
            tables[t]["comment"] = m.group(2).replace("''", "'")

    for parent, child, cols, _ in relations:
        if child in tables:
            for c in tables[child]["cols"]:
                if c["name"] in cols:
                    c["fk"] = True
    return tables, relations


def build_er_code(tables: dict, relations: list, show_columns: bool = True) -> str:
    out = ["erDiagram"]
    for name, t in tables.items():
        if not show_columns or not t["cols"]:
            out.append(f"    {name} {{\n    }}" if not show_columns else f"    {name}")
            continue
        out.append(f"    {name} {{")
        for c in t["cols"]:
            keys = ",".join(k for k, on in (("PK", c["pk"]), ("FK", c["fk"])) if on)
            comment = c["comment"].replace('"', "'")
            out.append("        " + " ".join(x for x in (c["type"], c["name"], keys, f'"{comment}"' if comment else "") if x))
        out.append("    }")
    for parent, child, cols, _ in relations:
        label = ", ".join(cols) or "FK"
        out.append(f'    {parent} ||--o{{ {child} : "{label}"')
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 循序圖
# ---------------------------------------------------------------------------

BLOCK_START = ("alt", "opt", "loop", "par", "critical", "break", "rect")
BLOCK_MIDDLE = ("else", "and", "option")


def build_sequence_code(lines_text: str, numbered: bool = False) -> str:
    ids, out = {}, []

    def pid(name: str) -> str:
        name = name.strip()
        if name not in ids:
            ids[name] = f"p{len(ids) + 1}"
        return ids[name]

    depth = 0
    for line in _lines(lines_text):
        low = line.lower()
        word = low.split()[0] if low.split() else ""
        if word in BLOCK_START:
            out.append("    " * (depth + 1) + f"{word} {_clean_plain(line[len(word):])}".rstrip())
            depth += 1
            continue
        if word in BLOCK_MIDDLE and depth:
            out.append("    " * depth + f"{word} {_clean_plain(line[len(word):])}".rstrip())
            continue
        if low == "end":
            if depth:
                depth -= 1
                out.append("    " * (depth + 1) + "end")
            continue
        nm = re.match(r"^(?:note|備註)\s+(.+?)\s*[:：]\s*(.+)$", line, re.I)
        if nm:
            who = [pid(w) for w in re.split(r"[,，、]", nm.group(1)) if w.strip()]
            out.append("    " * (depth + 1) + f"Note over {','.join(who[:2])}: {_clean_plain(nm.group(2))}")
            continue
        mm = re.match(r"^(.+?)\s*(-->|->|→)\s*(.+?)\s*(?:\s:\s|：|:)\s*(.*)$", line)
        if mm:
            a, arrow, b, msg = mm.groups()
            sym = "-->>" if arrow == "-->" else "->>"
            out.append("    " * (depth + 1) + f"{pid(a)}{sym}{pid(b)}: {_clean_plain(msg) or ' '}")
            continue
        mm = re.match(r"^(.+?)\s*(-->|->|→)\s*(.+?)$", line)
        if mm:
            a, arrow, b = mm.groups()
            out.append("    " * (depth + 1) + f"{pid(a)}{'-->>' if arrow == '-->' else '->>'}{pid(b)}: ")
    while depth:
        depth -= 1
        out.append("    " * (depth + 1) + "end")
    head = ["sequenceDiagram"] + (["    autonumber"] if numbered else [])
    head += [f"    participant {v} as {_clean_plain(k)}" for k, v in ids.items()]
    return "\n".join(head + out)


# ---------------------------------------------------------------------------
# 甘特圖
# ---------------------------------------------------------------------------

STATUS = {"完成": "done", "已完成": "done", "done": "done", "進行中": "active", "active": "active",
          "重要": "crit", "關鍵": "crit", "crit": "crit", "里程碑": "milestone", "milestone": "milestone"}


def build_gantt_code(title: str, tasks: str, exclude_weekends: bool = False) -> str:
    out = ["gantt", f"    title {_clean_plain(title) or '時程'}", "    dateFormat YYYY-MM-DD", "    axisFormat %m/%d"]
    if exclude_weekends:
        out.append("    excludes weekends")
    names, n = {}, 0
    for line in _lines(tasks):
        if line.startswith("##") or line.lower().startswith("section "):
            out.append(f"    section {_clean_plain(re.sub(r'^(##+|section)\s*', '', line, flags=re.I))}")
            continue
        cells = [c.strip() for c in re.split(r"\s*[|｜]\s*", line)]
        if len(cells) < 2:
            continue
        n += 1
        tid = f"t{n}"
        name = _clean_plain(cells[0]).replace(":", "：")
        names[cells[0]] = tid
        start = cells[1]
        sm = re.match(r"^(?:接續|after)\s*(.*)$", start, re.I)
        if sm:
            prev = sm.group(1).strip()
            start = f"after {names.get(prev, f't{n - 1}' if n > 1 else 't1')}"
        dur = cells[2] if len(cells) > 2 and cells[2] else "1d"
        dur = re.sub(r"^(\d+)\s*(天|日)$", r"\1d", dur)
        dur = re.sub(r"^(\d+)\s*(週|周)$", r"\1w", dur)
        dur = re.sub(r"^(\d+)\s*(小時)$", r"\1h", dur)
        status = [STATUS[s.strip().lower()] for s in re.split(r"[,，、]", cells[3]) if s.strip().lower() in STATUS] \
            if len(cells) > 3 else []
        if "milestone" in status:
            dur = "0d"
        meta = ", ".join(status + [tid, start, dur])
        out.append(f"    {name} :{meta}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 檢查與修正模型寫的 Mermaid
# ---------------------------------------------------------------------------

NODE_OPEN = [("([", "])"), ("[(", ")]"), ("[[", "]]"), ("((", "))"), ("{{", "}}"), ("[/", "/]"),
             ("[", "]"), ("(", ")"), ("{", "}"), (">", "]")]
NODE_ID_RE = re.compile(r"[\w\u4e00-\u9fff]+")


def _quote_labels(line: str) -> str:
    """把「節點ID[文字]」這類沒有引號的節點文字加上引號；用括號配對找結尾，文字裡有括號也不會切錯。"""
    out, i = [], 0
    while i < len(line):
        if line[i] == '"':  # 已經有引號的文字整段跳過
            end = line.find('"', i + 1)
            end = len(line) - 1 if end < 0 else end
            out.append(line[i:end + 1])
            i = end + 1
            continue
        m = NODE_ID_RE.match(line, i)
        if not m or (i > 0 and re.match(r"[\w\u4e00-\u9fff]", line[i - 1])):
            out.append(line[i])
            i += 1
            continue
        j = m.end()
        shape = next(((o, c) for o, c in NODE_OPEN if line.startswith(o, j)), None)
        if not shape or line.startswith('"', j + len(shape[0])):
            out.append(line[i:j])
            i = j
            continue
        o, c = shape
        k = j + len(o)
        end = -1
        if o == ">" or (len(o) == 2 and o[0] != o[1]):  # >文字]、([文字]) 等：找第一個結尾
            end = line.find(c, k)
        else:  # [文字]、((文字)) 等：只計算同一種括號的層數，文字裡有括號也能正確配對
            ch_open, ch_close = o[0], c[0]
            depth = len(o)
            for pos in range(k, len(line)):
                if line[pos] == ch_open:
                    depth += 1
                elif line[pos] == ch_close:
                    depth -= 1
                    if depth == 0:
                        end = pos - len(c) + 1
                        break
        if end < 0:
            out.append(line[i:j])
            i = j
            continue
        out.append(f"{line[i:j]}{o}{_q(line[k:end])}{c}")
        i = end + len(c)
    return "".join(out)



def check_mermaid_code(code: str) -> tuple:
    problems = []
    text = str(code).strip()
    fence = re.search(r"```(?:mermaid)?\s*\n(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    for bad, good in (("“", '"'), ("”", '"'), ("\t", "    "), ("－－＞", "-->"), ("——>", "-->"), ("—>", "-->")):
        if bad in text:
            text = text.replace(bad, good)
            problems.append(f"把全形或特殊符號「{bad}」改成「{good}」")

    lines = text.split("\n")
    first = next((l.strip() for l in lines if l.strip() and not l.strip().startswith("%%")), "")
    kind = first.split()[0] if first else ""
    if not kind:
        return "", ["內容是空的"]

    if kind in ("flowchart", "graph"):
        head_idx = next(i for i, l in enumerate(lines) if l.strip() == first)
        if len(first.split()) == 1:
            lines[head_idx] = f"{first} TD"
            problems.append("流程圖沒有方向，補上 TD（由上到下）")
        depth = 0
        for i, line in enumerate(lines):
            if i == head_idx:
                continue
            new = line.replace("→", "-->")
            # 單獨一行的 end 是 subgraph 結尾；其他地方的 end 當節點 ID 會出錯
            if new.strip() != "end" and re.search(r"(?<![\w\"])end(?![\w\"])", new):
                new = re.sub(r"(?<![\w\"])end(?![\w\"])", "end_node", new)
                problems.append(f"第 {i + 1} 行：`end` 是保留字，不能當節點 ID，改成 end_node")
            if re.search(r"-->\s*\|[^\"|][^|]*\|", new):
                new = re.sub(r"(-->|==>|-\.->)\s*\|(?!\")([^|]*)\|", lambda m: f'{m.group(1)}|{_q(m.group(2))}|', new)
                problems.append(f"第 {i + 1} 行：連線文字加上引號")
            if not new.strip().lower().startswith(("subgraph", "style", "classdef", "class ", "click", "linkstyle")):
                fixed = _quote_labels(new)
                if fixed != new:
                    problems.append(f"第 {i + 1} 行：節點文字加上引號，避免括號、冒號等符號破壞語法")
                    new = fixed
            # 箭頭前後補空白讓圖比較好讀（不處理 ---o、--x 這類本身就有意義的連線）
            spaced = re.sub(r"(?<=[\w\"\]\)\}])(-->|==>|-\.->)(?=[\w\"])", r" \1 ", new)
            if spaced != new:
                problems.append(f"第 {i + 1} 行：箭頭前後補上空白")
                new = spaced
            lines[i] = new
            s = new.strip().lower()
            if s.startswith("subgraph"):
                depth += 1
            elif s == "end":
                depth -= 1
        if depth > 0:
            lines += ["end"] * depth
            problems.append(f"subgraph 少了 {depth} 個 end，已補上")
        elif depth < 0:
            problems.append(f"end 比 subgraph 多了 {-depth} 個，請刪除多餘的 end")

    elif kind == "sequenceDiagram":
        depth = 0
        for i, line in enumerate(lines):
            s = line.strip()
            m = re.match(r"^(.+?(?:-->>|->>|-->|->|-x|--x|-\)|--\)))(.+?):(.*)$", s)
            if m and (";" in m.group(3) or "#" in m.group(3)):
                lines[i] = line.replace(m.group(3), _clean_plain(m.group(3)))
                problems.append(f"第 {i + 1} 行：訊息中的 ; 或 # 會破壞語法，改成全形")
            w = s.split()[0].lower() if s.split() else ""
            if w in BLOCK_START:
                depth += 1
            elif s == "end":
                depth -= 1
        if depth > 0:
            lines += ["end"] * depth
            problems.append(f"alt / loop / opt 等區塊少了 {depth} 個 end，已補上")

    elif kind == "erDiagram":
        for i, line in enumerate(lines):
            m = re.match(r"^(\s*)([A-Za-z][\w]*)\(([^)]*)\)(\s+\S+.*)$", line)
            if m:
                lines[i] = f"{m.group(1)}{m.group(2)}_{m.group(3).replace(',', '_').replace(' ', '')}{m.group(4)}"
                problems.append(f"第 {i + 1} 行：欄位型別的括號改成底線（舊版 Mermaid 不支援括號）")
        for i, line in enumerate(lines):
            m = re.match(r"^(\s*)([^\s{|}]*[^\w\s{|}][^\s{|}]*)(\s*\{)\s*$", line)
            if m:
                lines[i] = f"{m.group(1)}{_ident(m.group(2)) or 'TABLE'}{m.group(3)}"
                problems.append(f"第 {i + 1} 行：實體名稱改成只用英文、數字、底線（舊版 Mermaid 不支援其他符號）")

    elif kind == "gantt":
        if not any(l.strip().startswith("dateFormat") for l in lines):
            lines.insert(1, "    dateFormat YYYY-MM-DD")
            problems.append("甘特圖沒有 dateFormat，補上 YYYY-MM-DD")

    elif kind not in ("classDiagram", "stateDiagram", "stateDiagram-v2", "pie", "mindmap", "timeline",
                      "journey", "gitGraph", "quadrantChart", "xychart-beta", "block-beta", "sankey-beta"):
        problems.append(f"不認得的圖表類型「{kind}」，第一行應該是 flowchart、sequenceDiagram、erDiagram、gantt 等")

    return "\n".join(lines).strip(), problems


# ---------------------------------------------------------------------------
# Open WebUI 工具
# ---------------------------------------------------------------------------

class Tools:
    class Valves(BaseModel):
        MAX_TABLES: int = Field(default=30, description="ER 圖最多畫幾張表，太多會看不清楚")

    def __init__(self):
        self.valves = self.Valves()

    async def build_flowchart(self, steps: str, direction: str = "TD") -> str:
        """
        產生流程圖。每行寫一條流程，用箭頭 -> 連接，同一行可以連續寫多個步驟。
        連線文字寫在最後面的冒號後：「主管審核 -> 結束 : 同意」。
        虛線用 -.->，粗線用 ==>。節點形狀：{文字} 判斷、([文字]) 開始/結束、[(文字)] 資料庫、
        [[文字]] 子流程、[/文字/] 輸入輸出；「開始」「結束」與問號結尾的文字會自動套用形狀。
        可以用 subgraph 名稱 … end 分組。
        :param steps: 流程內容，一行一條，例如「開始 -> 填寫申請單 -> {主管審核}」換行「{主管審核} -> 結束 : 同意」
        :param direction: 方向，TD 由上到下、LR 由左到右
        """
        try:
            code = build_flowchart_code(steps, direction)
            return _code_block(code) if "-->" in code or "==>" in code or "-.->" in code else \
                "沒有找到任何連線。請用「步驟A -> 步驟B」的格式，一行一條。"
        except Exception as e:
            return f"產生流程圖失敗：{e}"

    async def build_er_diagram(self, ddl: str, show_columns: bool = True) -> str:
        """
        從 CREATE TABLE、ALTER TABLE ... FOREIGN KEY、COMMENT ON COLUMN 等 DDL 產生 ER 圖，
        自動標示主鍵（PK）、外鍵（FK）、欄位說明與表之間的關聯。
        :param ddl: 資料表的 DDL（可以多張表）
        :param show_columns: 是否列出欄位；表很多時設為 false 只畫表與關聯
        """
        try:
            tables, relations = parse_ddl(ddl)
            if not tables:
                return "沒有找到 CREATE TABLE 敘述。請提供資料表的 DDL。"
            note = []
            if len(tables) > self.valves.MAX_TABLES:
                keep = list(tables)[: self.valves.MAX_TABLES]
                tables = {k: tables[k] for k in keep}
                relations = [r for r in relations if r[0] in tables and r[1] in tables]
                note.append(f"> 表太多，只畫前 {self.valves.MAX_TABLES} 張。")
            missing = sorted({r[0] for r in relations if r[0] not in tables})
            if missing:
                note.append("> 外鍵參照的表沒有在 DDL 中：" + "、".join(missing) + "（圖中只會顯示表名）")
            note.append(f"> 共 {len(tables)} 張表、{len(relations)} 個外鍵關聯。")
            return _code_block(build_er_code(tables, relations, show_columns), "\n".join(note))
        except Exception as e:
            return f"產生 ER 圖失敗：{e}"

    async def build_sequence_diagram(self, messages: str, numbered: bool = False) -> str:
        """
        產生循序圖，適合畫系統之間的呼叫流程。每行一則訊息：「發送者 -> 接收者 : 訊息」，
        回應用虛線「接收者 --> 發送者 : 回應」。也可以寫「note 參與者 : 說明」，
        以及 alt 條件 / else 條件 / loop 條件 / opt 條件 … end 區塊。
        :param messages: 訊息內容，一行一則
        :param numbered: 是否幫每則訊息自動編號
        """
        try:
            code = build_sequence_code(messages, numbered)
            return _code_block(code) if "->>" in code else "沒有找到任何訊息。請用「A -> B : 訊息」的格式，一行一則。"
        except Exception as e:
            return f"產生循序圖失敗：{e}"

    async def build_gantt(self, title: str, tasks: str, exclude_weekends: bool = False) -> str:
        """
        產生甘特圖（專案時程）。每行一個任務：「任務名稱 | 開始日期 | 天數 | 狀態」。
        開始日期寫 YYYY-MM-DD，或「接續」（接在上一個任務後面）、「接續 任務名稱」。
        天數寫 5d、5天、2週，狀態可寫 完成、進行中、重要、里程碑（可省略）。
        用「## 區段名稱」分段。
        :param title: 甘特圖標題
        :param tasks: 任務清單，一行一個
        :param exclude_weekends: 是否跳過週末
        """
        try:
            code = build_gantt_code(title, tasks, exclude_weekends)
            return _code_block(code) if " :" in code else "沒有找到任何任務。請用「任務名稱 | 2026-12-01 | 5d」的格式。"
        except Exception as e:
            return f"產生甘特圖失敗：{e}"

    async def check_mermaid(self, code: str) -> str:
        """
        檢查並修正 Mermaid 程式碼的常見錯誤（節點文字的括號與冒號、保留字 end、全形符號、
        缺少的 end、ER 圖欄位型別的括號等）。自己寫了 Mermaid 或使用者貼上的圖顯示錯誤時使用。
        :param code: Mermaid 程式碼（可以包含 ```mermaid 標記）
        """
        try:
            fixed, problems = check_mermaid_code(code)
            if not fixed:
                return "沒有收到 Mermaid 程式碼。"
            if not problems:
                return (_code_block(fixed, "> 沒有發現常見錯誤。若畫面仍顯示錯誤，請把錯誤訊息貼上，"
                                           "或改用 build_flowchart 等工具重新產生。"))
            uniq = list(dict.fromkeys(problems))
            return _code_block(fixed, "已修正：\n" + "\n".join(f"- {p}" for p in uniq))
        except Exception as e:
            return f"檢查 Mermaid 失敗：{e}"
