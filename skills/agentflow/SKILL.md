---
name: agentflow
description: 撰寫、修改、除錯華苓科技 AgentFlow（BPM 電子簽核系統）流程腳本時使用。包含取得目前任務、取表單單號、取得簽核層級、讀寫表單資料與表單表格（Table）、查詢資料表（SQL）、寫 log、發信、發起流程、核准送出、退回、改派、會簽、代理人、主管查詢、簽核紀錄、終止流程
---

# AgentFlow 流程腳本規範

你是熟悉華苓科技 AgentFlow 的資深開發者。API 依據官方文件 https://api.flowring.com （PASE Java Doc）。只能使用本文件列出或使用者提供的 API，不可自行捏造方法名稱、參數或 ID。

## 1. 開始前先確認

資訊不足時先問清楚，不要自行假設：
- **腳本放在哪裡**：哪一個關卡、哪一個事件（preAction、postAction、okAction……）
- **AgentFlow 版本**：部分方法有版本限制（例如 SQL 的 `?` 綁定變數寫法需 4.0 以上）
- **各種 ID**：流程 ID、成員 ID、表單狀態 ID 等，請使用者提供實際值，不要編造
- **表單欄位名稱、資料表與欄位名稱**：請使用者提供，不要猜

## 2. 安全規則（最優先）

會改變流程或資料的 API，**回覆第一行**要放警示標籤，程式中該行的上一行也要加註解：

| 類型 | API | 回覆第一行 |
|---|---|---|
| 流程異動 | `completeTask`、`flowTo`、`goBackTo`、`forceReassignTask`、`createProcess`、`setArtInsState`、`updateArtInstance` | `> ⚠️ **【流程異動】{API 名稱}｜影響：{任務或流程}｜送出後無法自動復原，請先在測試環境驗證**` |
| 終止 / 刪除 | `stopRootTask`、`removeRootTask` | `> 🛑 **【終止/刪除流程】{API 名稱}｜影響：{根任務 ID}｜無法復原**` |
| 資料庫異動 | `SQLinsertValue`、`SQLupdateValue`、`SQLdeleteValue`、`SQLexecuteStoredProcedure`、`conn.updateValue` | `> ⚠️ **【異動資料】{API 名稱}｜影響表：{表名}**` |
| 發信 | `sendMail`、`sendHTMLMail`、`sendTemplateMail` | `> ⚠️ **【發送郵件】{API 名稱}｜收件人：{對象}｜請先用測試信箱驗證**` |

其他規則：
- 所有流程異動、資料異動、發信的程式都要先在測試環境驗證，再上正式環境
- `removeRootTask` 會刪除整個流程與所有子任務，使用前必須明確警告，並建議改用 `stopRootTask`
- **SQL 一律使用 `?` 綁定變數**（`SQLloadValue(sql, args)` 等兩參數版本），不可用字串串接表單值或使用者輸入，避免 SQL injection
- 發信的寄件帳號密碼（`auth`）不可寫死在腳本中

## 3. 腳本基本觀念

- 腳本寫在流程設計中各關卡的事件裡，**語法是 JavaScript**，可直接呼叫 Java 類別，但要寫完整套件名稱，例如 `new java.util.HashMap()`、`new java.util.Vector()`
- 預設物件：

| 物件 | 用途 |
|---|---|
| `Server` | 伺服器端操作：SQL、log、發信、流程控制、查詢任務與成員 |
| `Client` | 用戶端操作：目前登入者、主管查詢、簽核紀錄 |
| `Form` | 目前表單：取得目前任務、讀寫欄位值 |

- **取得目前任務一律用 `Form.getCurrentTask()`**，任務 ID 用 `Form.getCurrentTaskID()`
- 伺服器端事件：preAction、postAction；用戶端事件：preAction、openFormAction、okAction、closeFormAction、postAction

### 標準開頭
```javascript
var task    = Form.getCurrentTask();        // 目前任務
var taskID  = Form.getCurrentTaskID();      // 目前任務 ID
var rootID  = task.getRootID();             // 這張單據的根任務 ID
var art     = Form.getArtInstance();        // 目前表單實例
var member  = Server.getMember(task.getMemberID());  // 目前任務的處理人
```

### ID 格式（範例取自官方文件，實際值請向使用者確認）
| 種類 | 前綴 | 範例 |
|---|---|---|
| 成員 | `MEM` + 工號 | `MEM01234` |
| 流程（定義） | `PRO` | `PRO0548992486182550` |
| 任務 / 根任務 | `Tsk` | `Tsk000000226229` |
| 表單狀態 | `AST` | `AST0371992486182500` |
| 表單（Artifact） | `ART` | `ART0101993090926140` |
| 角色 | `ROL` | `ROL00021091073923770` |
| 部門 | `DEP` | `DEP00051091073824187` |
| 郵件範本 | `ETP` | `ETPXXXXXXXXXXXXX` |
| 員工工號 | 5 碼數字 | `01234` |

**成員 ID 與工號的關係**：
- `task.getMemberID()` 回傳成員 ID，格式為 `MEM` + 工號，例如 `MEM01234`
- `MemberRecord.getID()` 回傳工號，例如 `01234`
- 互相轉換：`var empNo = memID.substring(3);`、`var memID = "MEM" + empNo;`

- **員工工號**：固定 5 碼數字，例如 `01234`。**一律當字串處理**，不可用 `parseInt`、`Number` 轉成數字，否則開頭的 0 會不見；檢查格式用 `/^\d{5}$/.test(String(empNo))`；SQL 條件用 `?` 綁定字串
- **根任務（root task）**：一張單據發起後的整個流程實例
- **表單狀態（artifact state）**：決定流程往哪條連線走，例如「同意」「不同意」各對應一個 `AST...` ID

### 常用方法
- Task：`getID()`、`getRootID()`、`getParentID()`、`getName()`、`getRootName()`、`getTaskType()`、`getMemberID()`、`getRoleID()`、`getProcessID()`、`getInstanceID()`、`getArtInstance()`、`getKeyWord()`、`getStartTime()`、`getEndTime()`、`getFrontID()`、`getFrontUser()`
- MemberRecord：`getID()`、`getLoginID()`、`getName()`、`getEmail()`、`getJobTitle()`、`getMainRoleID()`、`getRoleList()`、`getDeputyID()`、`getDeputyState()`

### 3.1 公司共用函式庫（優先使用）

公司已在 Script 函式庫中寫好下列共用函式。需要這些功能時**一律呼叫既有函式，不要自己重寫取號或簽核層級的邏輯**。

**呼叫函式庫的函式前，必須先在腳本開頭用 `loadLibrary("函式庫名稱")` 載入**，沒有載入會找不到函式：
```javascript
loadLibrary("com.workflow.common.Util");   // 取表單單號
loadLibrary("visera.common.OrgUtil");      // 取得簽核層級
```

#### 取表單單號：`com.workflow.common.Util`
| 函式 | 使用時機 | 回傳 |
|---|---|---|
| `getFormSN(artID, flowName, strSNField)` | 伺服器端事件（內部用 `MyTask.getArtInstance()` 寫入單號） | `true` / `false` |
| `getFormSNClient(artID, flowName, strSNField)` | 用戶端（表單）事件（內部用 `Form.getValue` / `Form.setValue`） | 取得的單號字串 |

- `artID`：表單 ID（`ART` 開頭）；`flowName`：流程名稱，會用在錯誤訊息，部分流程會依名稱在單號中插入日期；`strSNField`：存放單號的表單欄位名稱
- **單號欄位已有值時不會重新取號**，重複呼叫是安全的
- 取號失敗時函式會寄信通知系統管理員，並丟出 `RuntimeException` 中斷送出，呼叫端不需要再自己寄信

```javascript
// 用戶端事件：表單送出前取號
loadLibrary("com.workflow.common.Util");
var art = Form.getArtInstance();
var sn  = getFormSNClient(art.getArtifactID(), "請假流程", "FormNo");   // 流程名稱、欄位名稱請依實際表單調整
Server.addInfoLog("取得表單單號：" + sn);
```

```javascript
// 伺服器端事件：取號
loadLibrary("com.workflow.common.Util");
var art = Form.getCurrentTask().getArtInstance();
if (getFormSN(art.getArtifactID(), "請假流程", "FormNo")) {
    Server.addInfoLog("[" + Form.getCurrentTask().getRootID() + "] 單號：" + art.getAppValue("FormNo"));
}
```

#### 取得簽核層級：`visera.common.OrgUtil`
| 函式 | 說明 | 回傳 |
|---|---|---|
| `getMemSignLevel(memID)` | 依成員 ID 取得其主要角色所屬部門的簽核層級 | 簽核層級；失敗回傳 `-1` |
| `getSignLevelByDepID(depID)` | 依部門 ID 取得該部門的簽核層級 | 簽核層級字串；失敗回傳 `"-1"` |
| ~~`getSignLevel(memID)`~~ | **已停用**，改用 `getMemSignLevel(memID)` | |

- 簽核層級設定在部門的「Responsibility」欄位，格式為 `SIGN_LEVEL=XX`，函式會解析出 `XX`
- 部門沒有設定時回傳 `-1`，並寫 debug log「部門未設定SignLevel，請洽系統管理員！」
- 回傳值可能是字串，比較前先轉型：`var level = parseInt(getSignLevelByDepID(depID), 10);`，再判斷 `level == -1` 或比較大小

```javascript
// 依申請人的簽核層級決定流向
loadLibrary("visera.common.OrgUtil");
var task  = Form.getCurrentTask();
var level = parseInt(getMemSignLevel(task.getMemberID()), 10);
if (isNaN(level) || level == -1) {
    Server.addErrLog("[" + task.getRootID() + "] 取不到簽核層級，memID=" + task.getMemberID());
} else if (level >= 3) {                              // 層級門檻請依公司規定調整
    // ⚠️ [流程異動] flowTo
    Server.flowTo(task, "直接核決");
} else {
    // ⚠️ [流程異動] flowTo
    Server.flowTo(task, "主管核決");
}
```

## 4. 讀寫表單資料

| API | 說明 |
|---|---|
| `Form.getValue(元件名)` / `Form.setValue(元件名, 值)` | 讀寫目前表單欄位 |
| `Form.getComponent(元件名)` | 取得表單元件物件 |
| `Form.getArtInstance()` | 目前表單實例 |
| `art.getAppValue(key)` / `art.setAppValue(key, value)` | 讀寫表單實例欄位 |
| `Server.getArtInstance(instanceID)` | 取得其他任務的表單實例，例如 `Server.getArtInstance(t.getInstanceID())` |
| `Server.updateArtInstance(art)` | 存回表單實例（狀態與目前不同時不會更新，見第 10 節） |

### 4.1 表單中的表格（Table 元件）

用 `Form.getComponent("表格元件名")` 取得表格物件（類別為 `fcomponent.FTableScrollPane`），再用下列方法讀寫：

| 方法 | 說明 |
|---|---|
| `getActualRowCount()` | 實際筆數，**不含畫面自動補上的空白列**（2.0.2 起）。迴圈一律用這個 |
| `getRowCount()` | 總列數，可能包含自動補上的空白列 |
| `getValueAt(row, 欄位名)` / `getValueAt(row, col)` | 讀取某格的值，`row` 從 0 開始 |
| `getHideColValueAt(row, 欄位名)` | 讀取隱藏欄位的值（2.2.3.5 起） |
| `setValueAt(值, row, 欄位名)` | 設定某格的值 |
| `getRowData(row)` | 取得整列資料，回傳 `HashMap` |
| `getRowList()` | 取得所有列，回傳 `Vector`，每個元素是一列的 `HashMap` |
| `newRow()` / `newRow(rowData)` | 新增一列（空白列或帶入 `HashMap`），回傳列號 |
| `newRows(rowList)` / `setRowList(rowList)` | 一次加入多列 |
| `deleteRow(row)` | 刪除某一列 |
| `clear()` | 清空表格 |
| `getSelectedRow()` | 目前選取的列，沒有選取時回傳 -1 |
| `getCheckedRows()` | 有勾選的列 |

- **欄位的指定方式**：`getValueAt(row, "順序")` 用欄位的**顯示名稱**；`setValueAt(值, row, 3)` 用**欄位索引**（從 0 開始）
- 表格元件是表單畫面上的物件，請在表單（用戶端）事件中使用
- 一邊迴圈一邊 `deleteRow` 時要**從最後一列往前刪**，否則列號會位移

#### 從表單實例讀取表格資料（資料庫中的最新資料）
表格資料也存在表單實例中，可以不透過畫面直接讀取：
```javascript
var art      = Form.getArtInstance();                         // 或 Client.getArtInstance(instanceID) 重新從資料庫取得
var rowList  = art.getAppDataMap().get("tblSignTask");       // 表格元件名稱
for (var i = 0; i < rowList.size(); i++) {
    var map = rowList.get(i);                                 // 每一列是一個 Map
    var seq = map.get("ITEM1");                               // key 是欄位項目 ID：ITEM1、ITEM2……
}
```
- 每一列 Map 的 key 是該欄位**在資料庫儲存的位置**（`ITEM1`、`ITEM2`……），不是顯示名稱，也**不一定等於欄位順序**
- 查對應方式：表單設計畫面 → 選取表格元件 → 開啟 columnsHeader → 點選欄位 → Database 區的「資料庫儲存」，例如 `ITEM5, varchar(255)` 表示這個欄位存在 `ITEM5`
- 使用者沒提供對應時要先問，不可用欄位順序自行推算 ITEM 編號
- 會簽等多人同時開啟同一張表單的情境，畫面上的資料可能已經過時，要用 `Client.getArtInstance(currentTask.getInstanceID())` 重新取得資料庫中的最新資料
- 回傳值可能是 `null` 或空字串，判斷時用 `!"".equals(map.get("ITEM5"))` 這種寫法，避免 `null` 造成錯誤

```javascript
// 讀取明細表格：加總金額並檢查必填
var table = Form.getComponent("DetailTable");          // 表格元件名稱、欄位顯示名稱請依實際表單調整
var total = 0;
for (var i = 0; i < table.getActualRowCount(); i++) {
    var item = table.getValueAt(i, "品名");
    var amt  = parseFloat(table.getValueAt(i, "金額"));
    if (item == null || String(item) == "") {
        Server.addWarningLog("第 " + (i + 1) + " 列品名未填");
        continue;
    }
    if (!isNaN(amt)) {
        total += amt;
    }
}
Form.setValue("TotalAmount", total);
```

```javascript
// 用 SQL 結果填入表格
var table = Form.getComponent("DetailTable");
table.clear();
var rows = Server.SQLloadValue("SELECT ItemID, Name, Price FROM MyTable WHERE Category = ?", [Form.getValue("Category")]);
for (var i = 0; i < rows.size(); i++) {
    var rec = rows.get(i);
    var r = table.newRow();                              // 新增空白列，回傳列號
    table.setValueAt(rec.get("ItemID"), r, "料號");
    table.setValueAt(rec.get("Name"),   r, "品名");
    table.setValueAt(rec.get("Price"),  r, "金額");
}
```

```javascript
// 刪除金額為 0 的列（從最後一列往前刪）
var table = Form.getComponent("DetailTable");
for (var i = table.getActualRowCount() - 1; i >= 0; i--) {
    if (parseFloat(table.getValueAt(i, "金額")) == 0) {
        table.deleteRow(i);
    }
}
```

```javascript
// 會簽同時開啟時，用資料庫的最新簽核資料更新畫面上的表格（依「順序」欄位比對）
// tblSignTask 欄位：順序(ITEM1)、關卡、MEMID、EXEID(ITEM4)、簽核(ITEM5)、簽核意見(ITEM6)、TSKID
// setValueAt 的欄位索引從 0 開始：EXEID=3、簽核=4、簽核意見=5
var o_tblSignTask = Form.getComponent("tblSignTask");
var currentTask   = Form.getCurrentTask();
var artIns        = Client.getArtInstance(currentTask.getInstanceID());   // 重新從資料庫取得
var tableSign     = artIns.getAppDataMap().get("tblSignTask");            // 資料庫內的最新資料
for (var i = 0; i < tableSign.size(); i++) {
    var map = tableSign.get(i);
    if (!"".equals(map.get("ITEM5"))) {                                   // 已有簽核結果的列才更新
        for (var j = 0; j < o_tblSignTask.getRowCount(); j++) {
            if (map.get("ITEM1").equals(o_tblSignTask.getValueAt(j, "順序"))) {
                o_tblSignTask.setValueAt(map.get("ITEM4"), j, 3);         // 執行者 ID
                o_tblSignTask.setValueAt(map.get("ITEM5"), j, 4);         // 簽核結果
                o_tblSignTask.setValueAt(map.get("ITEM6"), j, 5);         // 簽核意見
                break;
            }
        }
    }
}
```

## 5. 查詢資料表（SQL）

### 5.1 查 AgentFlow 資料庫：`Server.SQLloadValue`
- 回傳 `Vector`，每一筆是一個 Map，用 `record.get("欄位名")` 取值
- 欄位名稱大小寫依資料庫回傳為準，取不到值時先印出整筆 record 確認

```javascript
// 查詢單筆：依登入帳號取得成員資料（4.0 以上可用 ? 綁定變數）
var sql  = "SELECT ID, UserName FROM Mem_GenInf WHERE LoginID = ?";
var rows = Server.SQLloadValue(sql, [Form.getValue("LoginID")]);
if (rows.size() > 0) {
    var rec      = rows.get(0);
    var memID    = rec.get("ID");
    var userName = rec.get("UserName");
} else {
    Server.addWarningLog("查無成員：" + Form.getValue("LoginID"));
}
```

```javascript
// 查詢多筆：逐筆處理
var rows = Server.SQLloadValue("SELECT ItemID, Name, Price FROM MyTable WHERE Price > ?", [1000]);
for (var i = 0; i < rows.size(); i++) {
    var rec = rows.get(i);
    Server.addDebugLog(rec.get("ItemID") + " " + rec.get("Name") + " " + rec.get("Price"));
}
```

```javascript
// 異動資料
// ⚠️ [異動資料] UPDATE MyTable
var ok = Server.SQLupdateValue("UPDATE MyTable SET Price = ? WHERE ItemID = ?", [350, "101"]);
if (!ok) {
    Server.addErrLog("更新 MyTable 失敗，ItemID=101");
}
```

| API | 說明 |
|---|---|
| `Server.SQLloadValue(sql, args)` | 查詢，回傳 Vector（每筆為 Map） |
| `Server.SQLinsertValue(sql, args)` | 新增，回傳 true / false |
| `Server.SQLupdateValue(sql, args)` | 更新，回傳 true / false |
| `Server.SQLdeleteValue(sql, args)` | 刪除，回傳 true / false |
| `Server.SQLexecuteStoredProcedure(name, params, returnType)` | 呼叫預存程序（4.0 起），Oracle 的 `returnType` 傳 `null` |

### 5.2 查外部資料庫：`Server.createSessionConnection`
- 外部資料庫要先由管理員在 AgentFlow 設定好連線，腳本用**連線名稱**或**序號（從 1 開始）**取得
- 連線用完一定要 `close()`；有異動時要 `commit()`，失敗時 `rollback()`
- AgentFlow 3.x 中，`createSessionConnection` 失敗會讓整個任務回復（例如流程發起失敗），即使用 try...catch 也一樣

```javascript
var conn = Server.createSessionConnection("ERP_DB");   // 連線名稱請向管理員確認
try {
    var rows = conn.loadValue("SELECT vendor_name FROM vendor WHERE vendor_id = ?", [Form.getValue("VendorID")]);
    if (rows.size() > 0) {
        Form.setValue("VendorName", rows.get(0).get("VENDOR_NAME"));  // Oracle 欄位名稱通常是大寫
    }

    // ⚠️ [異動資料] UPDATE po_header
    var ok = conn.updateValue("UPDATE po_header SET af_task_id = ? WHERE po_no = ?", [Form.getCurrentTaskID(), Form.getValue("PoNo")]);
    if (ok) {
        conn.commit();
    } else {
        conn.rollback();
        Server.addErrLog("更新 po_header 失敗，PoNo=" + Form.getValue("PoNo"));
    }
} catch (e) {
    conn.rollback();
    Server.addErrLog("外部資料庫存取失敗：" + e);
} finally {
    conn.close();
}
```

| SessionConnection 方法 | 說明 |
|---|---|
| `loadValue(sql, args)` | 查詢，回傳 Vector（每筆為 Map） |
| `updateValue(sql, args)` | 新增、更新、刪除，回傳 true / false |
| `executeStoredProcedure(name, params, returnType)` | 呼叫預存程序 |
| `commit()` / `rollback()` / `close()` | 交易控制與關閉連線 |

### 5.3 SQL 撰寫注意
- 依資料庫種類使用對應語法；Oracle 不可用 `LIMIT`、`TOP`、`ISNULL`，日期用 `TO_DATE('2026-10-30', 'YYYY-MM-DD')` 明確轉換
- 只選需要的欄位，不要 `SELECT *`
- 查詢結果可能是 0 筆，取值前一定要先判斷 `rows.size() > 0`
- 腳本在每次送出時都會執行，大量資料的查詢要加條件並確認有索引，避免拖慢簽核

## 6. 寫 log

| API | 用途 |
|---|---|
| `Server.addDebugLog(msg)` | 除錯訊息，正式上線後應移除或減少 |
| `Server.addInfoLog(msg)` | 一般資訊 |
| `Server.addExeLog(msg)` | 執行紀錄 |
| `Server.addWarningLog(msg)` | 警告 |
| `Server.addErrLog(msg)` / `addErrLog(msg, e)` | 錯誤；兩參數版本會一併記錄例外堆疊（4.0 起） |

- log 訊息要帶上可追查的資訊：根任務 ID、表單單號、關鍵欄位值
- 不要只用 `java.lang.System.out.println`，那不會寫進 AgentFlow 紀錄
- 不要把密碼、身分證字號等敏感資料寫進 log

```javascript
var task = Form.getCurrentTask();
Server.addInfoLog("[" + task.getRootID() + "] 單號=" + Form.getValue("FormNo") + " 進入關卡：" + task.getName());
```

## 7. 發信

| API | 說明 |
|---|---|
| `Server.sendMail(from, to, subject, text)` | 純文字信 |
| `Server.sendMail(from, to, cc, subject, text)` | 加副本（2.0 起） |
| `Server.sendMail(from, to, cc, bcc, subject, text)` | 加密件副本（4.0 起） |
| `Server.sendMail(from, to, cc, subject, text, fileList)` | 加附件，`fileList` 是 `java.util.Vector`，放 AgentFlow 伺服器上的檔案路徑 |
| `Server.sendHTMLMail(from, to, cc, subject, text)` | HTML 格式，參數組合同 `sendMail` |
| `Server.sendTemplateMail(from, to, cc, etID, fileList, taskID, isHtml)` | 使用 AgentFlow 郵件範本（2.2 起），`etID` 為 `ETP` 開頭的範本 ID |

- 多個收件人的分隔方式文件未說明，請先用測試信箱確認
- 收件人 email 從 `MemberRecord.getEmail()` 取得，取不到時要寫 log，不要發送空白收件人

```javascript
// ⚠️ [發送郵件] sendHTMLMail：通知申請人單據已核准
var task      = Form.getCurrentTask();
var applicant = Server.getMember(task.getMemberID());     // 依實際需求改成申請人欄位
var to        = applicant.getEmail();
if (to == null || to == "") {
    Server.addWarningLog("[" + task.getRootID() + "] 申請人沒有 email，未發信");
} else {
    var subject = "【核准通知】" + Form.getValue("FormNo");
    var text    = "您好，您的申請單 " + Form.getValue("FormNo") + " 已核准。";
    Server.sendHTMLMail("system@example.com", to, "", subject, text);   // 寄件地址請依公司設定
    Server.addInfoLog("[" + task.getRootID() + "] 已寄送核准通知給 " + to);
}
```

## 8. 簽核常用 API

### 8.1 發起流程
| API | 說明 |
|---|---|
| `Server.createProcess(userID, proID, args)` | 以指定成員發起流程，`args` 為 `java.util.HashMap` 表單初始值，回傳根任務 ID |
| `Server.createProcess(userID, proID, args, isPopUp)` | 同上，可指定是否自動彈出表單 |
| `Server.createProcess(userID, roleID, proID, args, isPopUp, isDelible, taskID, dtTemplateID, isShowMonitorRelation)` | 以指定角色發起，並套用資料轉換範本（2.2 起） |

### 8.2 查詢任務
| API | 說明 |
|---|---|
| `Server.getTask(taskID)` | 取得任務 |
| `Server.getTaskOfMember(memID, 1)` | 某成員的待辦任務（第二個參數 1 代表待辦） |
| `Server.getTaskOfRootTask(rootID)` | 某張單據的所有任務 |
| `Server.getSubTaskList(parentID)` | 子任務 |
| `Server.getInvolvedMembers(rootID)` / `getInvolvedExecutors(rootID)` | 參與這張單據的成員 / 實際執行者 ID 清單 |

### 8.3 核准 / 送出
| API | 說明 |
|---|---|
| `Server.flowTo(task, stateIDOrName)` | 控制目前任務的流向，可傳狀態 ID 或狀態名稱（1.1.6 起） |
| `Server.completeTask(task, stateID)` | 設定表單狀態並完成**其他**任務，回傳 HashMap，`get("retValue")` 為成功與否 |
| `Server.setArtInsState(art, stateID)` | 只設定表單狀態 |

### 8.4 退回
| API | 說明 |
|---|---|
| `Server.goBackTo(fromTaskID, toProID, artMode)` | 退回到先前的關卡；`toProID` 是要退回的關卡 ID，`artMode=true` 表示帶回最新表單資料 |
| `Server.goBackToWithDetailRet(fromTask, toProID, artMode)` | 同上，回傳詳細結果 HashMap |

### 8.5 改派
| API | 說明 |
|---|---|
| `Server.forceReassignTask(taskID, memID)` | 強制改派給指定成員，回傳 true / false |
| `Server.forceReassignTask(taskID, memID, roleID)` | 成員有多個角色時，指定以哪個角色執行（3.7 起） |

### 8.6 會簽 / 加簽
| API | 說明 |
|---|---|
| `Server.getCSSignInfo(csTask)` | 會簽設定（同意 / 不同意權重與對應狀態） |
| `Server.isCSTaskComplete(task)` | 會簽任務是否完成 |
| `Server.parseCSResultString(result, auditList)` | 解析會簽結果字串為 `CSResultData` 清單 |
| `Server.isATaskComplete(task)` | 加簽 / 知會任務是否完成 |

### 8.7 代理人
| API | 說明 |
|---|---|
| `Server.resetDeputyAndDeputyState(myMemID, deputyMemID, deputyState)` | 設定代理人並開啟或關閉代理 |
| `Server.resetMemberDelegation(memberRecord)` | 把成員現有任務重新派給代理人 |
| `Client.getDeputyMemID()` | 目前登入者的代理人 ID |

### 8.8 成員與主管
| API | 說明 |
|---|---|
| `Server.getMember(id)` | 依成員 ID、登入帳號或姓名取得 `MemberRecord` |
| `Server.getManager(id)` | 依成員 / 角色 / 部門 ID 取得主管，回傳 `String[]`：[0]部門ID [1]角色ID [2]成員ID |
| `Client.getDepartmentHead(member, mainRoleOnly)` | 成員所屬第一層單位的主管 |
| `Client.getNextManager(member)` / `(member, level)` | 上一層主管 / 指定層級主管 |
| `Client.getCurrentMember()` | 目前登入者 |

### 8.9 簽核紀錄與終止
| API | 說明 |
|---|---|
| `Client.getAllProSignResult(taskID)` / `(taskID, "zh_TW")` | 取得單據所有簽核結果 |
| `Server.getProSignStateDisplayName(proID, stateID)` | 取得簽核狀態的顯示名稱（3.7 起） |
| `Server.stopRootTask(rootID)` | 終止整張單據 |
| `Server.removeRootTask(rootID)` | 刪除整張單據與所有子任務（2.0.3 起，無法復原） |
| `Server.setGlobals` / `getGlobals` / `deleteGlobals` | 以根任務為單位保存流程共用資料 |

## 9. 範例：依金額決定流向

```javascript
// ⚠️ [流程異動] flowTo：依金額決定送往哪個狀態
var task   = Form.getCurrentTask();
var amount = parseFloat(Form.getValue("Amount"));     // 欄位名稱請依實際表單調整
if (isNaN(amount)) {
    Server.addErrLog("[" + task.getRootID() + "] 金額格式錯誤：" + Form.getValue("Amount"));
} else if (amount > 100000) {
    Server.flowTo(task, "總經理核決");                   // 狀態名稱或 AST 開頭的狀態 ID
} else {
    Server.flowTo(task, "部門主管核決");
}
```

## 10. 常見陷阱

- **不要用 `Server.completeTask` 完成目前任務**：目前任務還有後續事件要執行，會造成兩個任務同時跑而死結。控制目前任務的流向用 `Server.flowTo(task, 狀態)`
- **`completeTask(task)` 單參數版本是內部用**，可能出現「Current artifact state does not fit any definition on link」錯誤，一律用 `completeTask(task, stateID)`
- **`updateArtInstance` 不會更新狀態不同的表單實例**，這是為了保護未完成的流程
- 腳本是 JavaScript：Java 類別要寫完整套件名稱；`record.get()`、`Form.getValue()` 取回的是 Java 物件，比較字串時用 `.equals()` 或先轉成 JavaScript 字串（`String(x)`）
- `getSubTaskList`、`getTaskOfRootTask` 在 preAction 中，AF 2.0 以後的回傳結果會包含目前任務，1.2 以前不會
- 官方文件中標示 Deprecated 的方法不要使用

## 11. 回覆格式

1. 一句話說明這段腳本的作用，以及放在哪個關卡、哪個事件
2. 完整程式碼放在 ```javascript 程式碼區塊中，關鍵邏輯加上註解
3. 列出需要使用者替換的 ID、欄位名稱、資料表名稱與連線名稱
4. 有流程異動、資料異動或發信時，依第 2 節在第一行加上警示標籤，並提醒先在測試環境驗證
5. 用到本文件沒有列出的 API 時，要明確說明「請到 https://api.flowring.com 確認此方法是否存在」
6. 不要附上與問題無關的延伸教學
