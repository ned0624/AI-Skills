# 模型系統提示詞

## system-prompt.md — 技能與工具使用總覽

告訴模型有哪些技能和工具、什麼情境該用哪一個、衝突時的優先順序。

### 為什麼放在系統提示詞，而不是做成一個 skill

新版 Open WebUI 掛在模型上的技能，預設只會把**名稱與說明**放進對話，完整內容要模型自己呼叫 `view_skill` 才會讀取。
總覽如果也做成 skill，模型可能根本不會去讀它。放在系統提示詞中，每次對話都一定看得到，模型才知道什麼時候該讀哪個技能。

### 安裝

1. **工作區 → 模型**，編輯要使用的模型
2. 把 `system-prompt.md` 的內容貼到 **系統提示詞（System Prompt）**
3. 確認表格中的技能名稱（`read-attachments`、`oracle-sql` 等）和 Open WebUI 技能清單中的 ID 一致；不一致時改成實際的 ID
4. 確認模型已勾選 Office File Reader、Kettle Reader、Mermaid Builder 三個工具，Function Calling 設為 **Native**

### 維護

- 新增或刪除技能、工具時，同步更新第 2、3 節的表格
- 內容保持精簡，只放「選擇哪個技能」與「優先順序」；各技能的細節留在技能本身，不要重複寫在這裡
- 系統提示詞每次對話都會送出，內容穩定不變時，推論伺服器的前綴快取（prefix caching）效果最好
