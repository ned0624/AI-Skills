"""
title: Mermaid Builder
description: 產生語法正確的 Mermaid 圖（流程圖、從 DDL 產生 ER 圖），以及檢查修正 Mermaid 的常見錯誤。Open WebUI 會直接把 mermaid 程式碼區塊畫成圖
version: 2.0.0
license: MIT
"""

import re


def _q(text: str) -> str:
    """文字一律加雙引號，裡面的雙引號改成 Mermaid 的跳脫寫法。"""
    return '"' + str(text).strip().replace('"', "#quot;") + '"'


def _reply(code: str, note: str = "") -> str:
    return ("請把下面的程式碼區塊原封不動放進回覆：\n\n```mermaid\n" + code.strip() + "\n```"
            + (f"\n\n{note}" if note else ""))


# ---------------------------------------------------------------------------
# 流程圖：「A -> B -> C : 連線文字」
# ---------------------------------------------------------------------------

def flowchart(steps: str, direction: str = "TD") -> str:
    ids, out = {}, []

    def node(token: str) -> str:
        t = token.strip()
        if t.startswith("{") and t.endswith("}"):
            text, shape = t[1:-1], ("{", "}")
        elif t.startswith("[(") and t.endswith(")]"):
            text, shape = t[2:-2], ("[(", ")]")
        elif t in ("開始", "結束", "完成") or t.lower() in ("start", "end"):
            text, shape = t, ("([", "])")
        elif t.endswith(("?", "？")):
            text, shape = t, ("{", "}")
        else:
            text, shape = t, ("[", "]")
        text = text.strip()
        if text in ids:
            return ids[text]
        ids[text] = f"n{len(ids) + 1}"
        return f"{ids[text]}{shape[0]}{_q(text)}{shape[1]}"  # 第一次出現時定義節點

    depth = 0
    for line in str(steps).splitlines():
        line = line.strip()
        if line.lower().startswith("subgraph "):  # 分組開始，例如「subgraph 主作業」
            out.append("    " * (depth + 1) + f"subgraph g{len(out)}[{_q(line[9:])}]")
            depth += 1
            continue
        if line.lower() == "end" and depth:
            depth -= 1
            out.append("    " * (depth + 1) + "end")
            continue
        if not line or "->" not in line and "→" not in line:
            continue
        parts = re.split(r"\s*(-\.->|-+>|→)\s*", line)  # -.-> 虛線；->、-->、→ 實線
        label = ""
        m = re.match(r"^(.*?)\s*[:：]\s*(.+)$", parts[-1])
        if m:
            parts[-1], label = m.group(1), m.group(2)
        names = [node(p) for p in parts[0::2]]
        for i, arrow in enumerate(parts[1::2]):
            arrow = "-.->" if arrow == "-.->" else "-->"
            text = label if i == len(names) - 2 else ""
            mid = f" {arrow}|{_q(text)}| " if text else f" {arrow} "
            left = names[i] if i == 0 else names[i].split("[")[0].split("(")[0].split("{")[0]  # 已定義過只寫 ID
            out.append("    " * (depth + 1) + f"{left}{mid}{names[i + 1]}")
    while depth:
        depth -= 1
        out.append("    " * (depth + 1) + "end")
    if not any("--" in line for line in out):
        return ""
    direction = direction.upper() if direction.upper() in ("TD", "LR") else "TD"
    return f"flowchart {direction}\n" + "\n".join(out)


# ---------------------------------------------------------------------------
# ER 圖：從 DDL 解析表、欄位、主鍵、外鍵、欄位說明
# ---------------------------------------------------------------------------

def _name(text: str) -> str:
    return re.sub(r"[^A-Z0-9_]", "_", text.strip().strip('"`').split(".")[-1].upper())


def _names(text: str) -> list:
    return [_name(c) for c in (text or "").split(",") if c.strip()]


def er_diagram(ddl: str) -> str:
    sql = re.sub(r"--[^\n]*|/\*.*?\*/", " ", str(ddl), flags=re.S)
    tables, fks = {}, []  # tables: {表: {欄位: {"type","pk","note"}}}；fks: (父表, 子表, 欄位)

    for m in re.finditer(r"create\s+table\s+([\w.\"$#`]+)\s*\(", sql, re.I):
        table, depth, i = _name(m.group(1)), 1, m.end()
        while i < len(sql) and depth:
            depth += {"(": 1, ")": -1}.get(sql[i], 0)
            i += 1
        cols = tables.setdefault(table, {})
        # 依最外層的逗號切開每個欄位或限制
        items, depth, cur = [], 0, ""
        for ch in sql[m.end():i - 1] + ",":
            depth += {"(": 1, ")": -1}.get(ch, 0)
            if ch == "," and depth == 0:
                items.append(cur.strip())
                cur = ""
            else:
                cur += ch
        for item in filter(None, items):
            pk = re.search(r"^(?:constraint\s+\S+\s+)?primary\s+key\s*\(([^)]*)\)", item, re.I)
            fk = re.search(r"^(?:constraint\s+\S+\s+)?foreign\s+key\s*\(([^)]*)\)\s*references\s+([\w.\"$#`]+)", item, re.I)
            if pk:
                for c in _names(pk.group(1)):
                    cols.setdefault(c, {"type": "", "note": ""})["pk"] = True
            elif fk:
                fks.append((_name(fk.group(2)), table, _names(fk.group(1))))
            elif not re.match(r"(constraint|unique|check)\b", item, re.I):
                col = re.match(r"([\w\"$#`]+)\s+([A-Za-z]\w*)(\s*\([^)]*\))?(.*)$", item, re.S)
                if col:
                    size = re.sub(r"[^0-9,]", "", col.group(3) or "").replace(",", "_")
                    info = cols.setdefault(_name(col.group(1)), {"note": ""})
                    info["type"] = col.group(2).upper() + (f"_{size}" if size else "")
                    info["pk"] = info.get("pk") or bool(re.search(r"primary\s+key", col.group(4), re.I))
                    ref = re.search(r"references\s+([\w.\"$#`]+)", col.group(4), re.I)
                    if ref:
                        fks.append((_name(ref.group(1)), table, [_name(col.group(1))]))

    for m in re.finditer(r"alter\s+table\s+([\w.\"$#`]+)\s+add\s+(?:constraint\s+\S+\s+)?(primary|foreign)\s+key\s*"
                         r"\(([^)]*)\)(?:\s*references\s+([\w.\"$#`]+))?", sql, re.I):
        table, cols = _name(m.group(1)), _names(m.group(3))
        if m.group(2).lower() == "foreign" and m.group(4):
            fks.append((_name(m.group(4)), table, cols))
        elif table in tables:
            for c in cols:
                tables[table].setdefault(c, {"type": "", "note": ""})["pk"] = True
    for m in re.finditer(r"comment\s+on\s+column\s+([\w.\"$#`]+)\s+is\s+'((?:[^']|'')*)'", sql, re.I):
        parts = m.group(1).split(".")
        table, col = (_name(parts[-2]), _name(parts[-1])) if len(parts) > 1 else ("", "")
        if col in tables.get(table, {}):
            tables[table][col]["note"] = m.group(2).replace("''", "'").replace('"', "'")
    if not tables:
        return ""

    fk_cols = {(child, c) for _, child, cols in fks for c in cols}
    out = ["erDiagram"]
    for table, cols in tables.items():
        if len(tables) > 10:  # 表太多時只畫表名與關聯，圖才看得清楚
            out.append(f"    {table}")
            continue
        out.append(f"    {table} {{")
        for col, info in cols.items():
            keys = ",".join(k for k, on in (("PK", info.get("pk")), ("FK", (table, col) in fk_cols)) if on)
            note = f'"{info["note"]}"' if info.get("note") else ""
            out.append("        " + " ".join(x for x in (info.get("type") or "UNKNOWN", col, keys, note) if x))
        out.append("    }")
    out += [f'    {parent} ||--o{{ {child} : "{", ".join(cols)}"' for parent, child, cols in fks]
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 檢查修正：模型自己寫的 Mermaid 常見錯誤
# ---------------------------------------------------------------------------

SHAPES = [("([", "])"), ("[(", ")]"), ("[[", "]]"), ("((", "))"), ("{{", "}}"), ("[", "]"), ("(", ")"), ("{", "}")]


def _quote_nodes(line: str) -> str:
    """節點ID後面沒加引號的文字補上引號；用括號配對找結尾，文字裡有括號也不會切錯。"""
    out, i = "", 0
    while i < len(line):
        if line[i] == '"':  # 已有引號的文字整段跳過
            j = line.find('"', i + 1)
            j = len(line) - 1 if j < 0 else j
            out, i = out + line[i:j + 1], j + 1
            continue
        m = re.match(r"[\w一-鿿]+", line[i:])
        shape = m and next((s for s in SHAPES if line.startswith(s[0], i + m.end())), None)
        if not shape or (i and re.match(r"[\w一-鿿]", line[i - 1])) or \
                line.startswith('"', i + m.end() + len(shape[0])):
            out, i = out + line[i], i + 1
            continue
        start = i + m.end() + len(shape[0])
        if shape[0][0] != shape[0][-1]:  # ([文字])、[(文字)]：找第一個結尾
            end = line.find(shape[1], start)
        else:  # [文字]、((文字))：只計算同一種括號，文字裡有括號也能正確配對
            depth, end = len(shape[0]), -1
            for pos in range(start, len(line)):
                depth += (line[pos] == shape[0][0]) - (line[pos] == shape[1][0])
                if depth == 0:
                    end = pos - len(shape[1]) + 1
                    break
        if end < 0:
            out, i = out + line[i], i + 1
            continue
        out += m.group(0) + shape[0] + _q(line[start:end]) + shape[1]
        i = end + len(shape[1])
    return out


def check(code: str) -> tuple:
    text = str(code).strip()
    fence = re.search(r"```(?:mermaid)?\s*\n(.*?)```", text, re.S)
    text = (fence.group(1) if fence else text).strip()
    for bad, good in (("“", '"'), ("”", '"'), ("→", "-->"), ("－－＞", "-->"), ("\t", "    ")):
        text = text.replace(bad, good)
    lines, fixes = text.splitlines(), []
    kind = lines[0].split()[0] if lines and lines[0].split() else ""

    if kind in ("flowchart", "graph"):
        if len(lines[0].split()) == 1:
            lines[0] += " TD"
            fixes.append("補上方向 TD")
        for n, line in enumerate(lines[1:], 2):
            new = line
            if new.strip() != "end":
                new = re.sub(r"(?<![\w\"])end(?![\w\"])", "end_node", new)  # end 是保留字
            new = re.sub(r"(-->|==>|-\.->)\s*\|(?!\")([^|]*)\|", lambda m: f"{m.group(1)}|{_q(m.group(2))}|", new)
            if not new.strip().lower().startswith(("subgraph", "style", "classdef", "class ", "click", "linkstyle")):
                new = _quote_nodes(new)
            if new != line:
                fixes.append(f"第 {n} 行：文字加上引號" + ("，保留字 end 改成 end_node" if "end_node" in new else ""))
                lines[n - 1] = new
        opened = sum(l.strip().lower().startswith("subgraph") for l in lines)
        closed = sum(l.strip() == "end" for l in lines)
        if opened > closed:
            lines += ["end"] * (opened - closed)
            fixes.append(f"補上 {opened - closed} 個 subgraph 的 end")

    elif kind == "sequenceDiagram":
        for n, line in enumerate(lines[1:], 2):
            m = re.match(r"^(.*?(?:->>|-->>|->|-->|-x|--x)[^:]+:)(.*)$", line)
            if m and re.search(r"[;#]", m.group(2)):
                lines[n - 1] = m.group(1) + m.group(2).replace(";", "；").replace("#", "＃")
                fixes.append(f"第 {n} 行：訊息中的 ; 和 # 改成全形")
        opened = sum(bool(re.match(r"\s*(alt|opt|loop|par|critical|break|rect)\b", l)) for l in lines)
        closed = sum(l.strip() == "end" for l in lines)
        if opened > closed:
            lines += ["end"] * (opened - closed)
            fixes.append(f"補上 {opened - closed} 個 alt / loop / opt 的 end")
    return "\n".join(lines), fixes


# ---------------------------------------------------------------------------
# Open WebUI 工具
# ---------------------------------------------------------------------------

class Tools:
    async def draw_mermaid(self, kind: str, content: str, direction: str = "TD") -> str:
        """
        產生語法正確的 Mermaid 圖。
        kind="流程圖"：content 一行一條流程，用 -> 連接（失敗或例外路徑用虛線 -.->），連線文字寫在冒號後，例如
          「開始 -> 填寫請假單 -> {主管審核}」換行「{主管審核} -> 結束 : 同意」。
          {文字} 是判斷、[(文字)] 是資料庫；開始、結束與問號結尾的文字會自動套用形狀。
          要分組時用「subgraph 名稱」開始、「end」結束。
        kind="ER圖"：content 放資料表的 DDL（CREATE TABLE、ALTER TABLE ... FOREIGN KEY、COMMENT ON COLUMN）。
        :param kind: 流程圖 或 ER圖
        :param content: 流程內容或 DDL
        :param direction: 流程圖方向，TD 由上到下、LR 由左到右
        """
        if "er" in kind.lower():
            code = er_diagram(content)
            return _reply(code) if code else "沒有找到 CREATE TABLE，請提供資料表的 DDL。"
        code = flowchart(content, direction)
        return _reply(code) if code else "沒有找到流程，請用「步驟A -> 步驟B」的格式，一行一條。"

    async def check_mermaid(self, code: str) -> str:
        """
        檢查並修正自己寫的或使用者貼上的 Mermaid（循序圖、甘特圖、圓餅圖等都可以），
        會處理節點文字的括號與冒號、保留字 end、全形符號、訊息中的 ; 和 #、少了 end 等常見錯誤。
        :param code: Mermaid 程式碼
        """
        fixed, fixes = check(code)
        if not fixed:
            return "沒有收到 Mermaid 程式碼。"
        return _reply(fixed, "已修正：" + "、".join(dict.fromkeys(fixes)) if fixes else "沒有發現常見錯誤。")
