---
name: mermaid
description: 需要畫圖說明時使用：流程圖、簽核流程、資料表關聯（ER 圖，可直接從 DDL 產生）、系統之間的呼叫順序（循序圖）、專案時程（甘特圖），或使用者貼上的 Mermaid 圖顯示錯誤時。Open WebUI 會把 mermaid 程式碼區塊直接畫成圖
---

# Mermaid 畫圖規範

Open WebUI 會把 ```mermaid 程式碼區塊直接畫成圖。

> ⚠️ **最重要的規則：回覆中的每一個 mermaid 程式碼區塊，都必須來自工具的回傳結果。**
> 不可以自己手寫後直接輸出。自己寫的（循序圖、甘特圖等）一定要先交給 `check_mermaid`，再輸出工具回傳的版本。
> 常見的顯示失敗原因：連線文字 `|Yes (正式出貨)|` 或節點文字含括號、冒號卻沒加引號，工具會自動處理。

用 **Mermaid Builder** 的兩個工具：

| 要畫的圖 | 做法 |
|---|---|
| 流程圖、簽核流程、ETL 流程 | `draw_mermaid(kind="流程圖", content=...)` |
| 資料表關聯（有 DDL） | `draw_mermaid(kind="ER圖", content=DDL)` |
| 循序圖、甘特圖、其他圖 | 照第 3 節的範本自己寫，**寫完一定要交給 `check_mermaid` 檢查** |
| 使用者貼上的圖顯示錯誤 | `check_mermaid(code=...)` |

## 1. 流程圖

一行一條流程，用 `->` 連接，連線文字寫在冒號後面：
```
開始 -> 填寫請假單 -> {主管審核}
{主管審核} -> 人資登錄 : 同意
{主管審核} -> 填寫請假單 : 退回
人資登錄 -> [(HR 資料庫)] -> 結束
```
- `{文字}` 判斷，`[(文字)]` 資料庫；「開始」「結束」和問號結尾的文字會自動套用形狀
- 失敗或例外路徑用虛線 `-.->`，例如 `寫入資料 -.-> 寄送警示信 : 失敗`
- 分組：`subgraph 名稱` 開始、`end` 結束（例如一個作業一組）
- 文字裡可以有括號、冒號、引號，工具會處理，不用自己跳脫
- 同一個節點每次都要寫完全相同的文字，否則會變成兩個節點
- 步驟多用 `direction="TD"`（由上到下），步驟少用 `"LR"`（由左到右）

## 2. ER 圖

直接把 DDL（CREATE TABLE、ALTER TABLE ... FOREIGN KEY、COMMENT ON COLUMN）放進 `content`，工具會標示 PK、FK、欄位說明與表之間的關聯。超過 10 張表時只畫表名與關聯。
沒有 DDL 時請使用者提供，不要自己編造欄位。

## 3. 自己寫的圖（寫完交給 check_mermaid）

循序圖：
```
sequenceDiagram
    participant U as 使用者
    participant A as AgentFlow
    U->>A: 送出請假單
    A-->>U: 回傳結果
    alt 天數足夠
        A->>U: 通知主管簽核
    else 天數不足
        A-->>U: 退回
    end
```
- `->>` 呼叫，`-->>` 回應；`alt`、`loop`、`opt` 最後一定要有 `end`

甘特圖：
```
gantt
    title 專案時程
    dateFormat YYYY-MM-DD
    section 需求
    需求訪談 :done, t1, 2026-12-01, 5d
    規格確認 :active, t2, after t1, 3d
    上線 :milestone, t3, 2026-12-31, 0d
```
- 每個任務：`名稱 :狀態, 代號, 開始日期或 after 代號, 天數`，狀態可省略（done 完成、active 進行中、crit 重要、milestone 里程碑）

## 4. 回覆規則

1. 工具回傳的 mermaid 程式碼區塊**原封不動**放進回覆，不要修改
2. 圖的前後用一兩句話說明圖在表達什麼
3. 一張圖不超過約 25 個節點，太複雜就拆成多張
4. 圖中使用實際的步驟名稱、表名、系統名稱
5. Kettle 的流程圖直接用 Kettle Reader 產生的圖（上傳多個檔案時有「整體流程圖」），不要自己重畫
6. 使用者說圖顯示錯誤時，把整段 mermaid 交給 `check_mermaid`，輸出修正後的版本
