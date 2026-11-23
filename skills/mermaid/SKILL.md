---
name: mermaid
description: 需要畫圖說明時使用：流程圖、簽核流程、系統之間的呼叫順序（循序圖）、資料表關聯（ER 圖，可直接從 DDL 產生）、專案時程（甘特圖），或使用者貼上的 Mermaid 圖顯示錯誤時。用 Mermaid Builder 工具產生語法正確的 Mermaid 程式碼，Open WebUI 會直接畫成圖
---

# Mermaid 畫圖規範

Open WebUI 會把 ```mermaid 程式碼區塊直接畫成圖。**不要自己手寫 Mermaid**，括號、冒號、保留字很容易寫錯而讓圖顯示失敗。一律用 **Mermaid Builder** 工具產生，再把結果原封不動放進回覆。

## 1. 選擇圖的類型

| 要表達的內容 | 工具 |
|---|---|
| 步驟、判斷、簽核流程、ETL 流程 | `build_flowchart` |
| 系統或人員之間的呼叫、回應順序（API、AgentFlow 與 ERP 的互動） | `build_sequence_diagram` |
| 資料表之間的關聯（使用者提供 DDL） | `build_er_diagram` |
| 專案時程、工作排程 | `build_gantt` |
| 使用者貼上的 Mermaid 顯示錯誤，或要畫上面沒有的圖（圓餅圖、心智圖、狀態圖等） | 先寫好 Mermaid，再用 `check_mermaid` 檢查修正 |

## 2. 各工具的輸入格式

### build_flowchart(steps, direction)
一行一條流程，用 `->` 連接，同一行可以連續寫多個步驟；連線文字寫在最後的冒號後面。
```
開始 -> 填寫請假單 -> {主管審核}
{主管審核} -> 人資登錄 : 同意
{主管審核} -> 填寫請假單 : 退回
人資登錄 -> [(HR 資料庫)] -> 結束
```
- 節點形狀：`{文字}` 判斷、`([文字])` 開始/結束、`[(文字)]` 資料庫、`[[文字]]` 子流程、`[/文字/]` 輸入輸出；「開始」「結束」和問號結尾的文字會自動套用形狀
- 同一個節點每次都要寫**完全相同的文字**（形狀標記只需要寫一次），否則會變成兩個節點
- 虛線 `-.->`（選擇性、非同步），粗線 `==>`（主要路徑）
- 分組：`subgraph 名稱` 開始，`end` 結束
- `direction`：步驟多、由上往下用 `TD`；步驟少、橫向比較好看用 `LR`

### build_sequence_diagram(messages, numbered)
```
使用者 -> AgentFlow : 送出請假單
AgentFlow -> ERP : 查詢剩餘特休
ERP --> AgentFlow : 回傳天數
alt 天數足夠
AgentFlow -> 主管 : 通知簽核
else 天數不足
AgentFlow --> 使用者 : 退回
end
note 主管 : 3 天內需簽核
```
- `->` 呼叫（實線），`-->` 回應（虛線）
- 區塊：`alt 條件` / `else 條件` / `loop 條件` / `opt 條件`，最後一定要有 `end`

### build_er_diagram(ddl, show_columns)
直接傳入 DDL（CREATE TABLE、ALTER TABLE ... FOREIGN KEY、COMMENT ON COLUMN），工具會自動標示 PK、FK、欄位說明與表之間的關聯。
- 超過 10 張表時，`show_columns=false` 只畫表與關聯，圖才看得清楚
- 使用者沒有提供 DDL 時，請使用者提供（或執行 `DBMS_METADATA.GET_DDL` 取得），不要自己編造欄位

### build_gantt(title, tasks, exclude_weekends)
```
## 需求
需求訪談 | 2026-12-01 | 5天 | 完成
規格確認 | 接續 | 3d | 進行中
## 開發
Kettle 開發 | 接續 需求訪談 | 2週 | 重要
上線 | 2026-12-31 | 0d | 里程碑
```
- 格式：`任務名稱 | 開始日期 | 天數 | 狀態`，狀態可省略
- 開始日期：`YYYY-MM-DD`，或「接續」（接在上一個任務後）、「接續 任務名稱」

### check_mermaid(code)
傳入 Mermaid 程式碼，工具會修正常見錯誤（節點文字裡的括號與冒號、保留字 `end`、全形符號、少了 `end`），並列出修改了哪些地方。

## 3. 回覆規則

1. **工具回傳的 mermaid 程式碼區塊要原封不動放進回覆**，不可以修改、重新排版或刪減
2. 圖的前後用一兩句話說明圖在表達什麼，不要逐行解釋程式碼
3. 一張圖不要超過約 25 個節點；流程太複雜時拆成多張圖（例如「整體流程」＋「審核細節」）
4. 圖中的名稱用實際的步驟名稱、表名、系統名稱，不要自己改寫
5. 使用者說圖顯示錯誤時，把使用者貼的程式碼交給 `check_mermaid`；仍然失敗就改用 `build_*` 工具重新產生
6. Kettle Reader 的流程摘要已經附有 mermaid 流程圖，可以直接沿用，不需要重畫
