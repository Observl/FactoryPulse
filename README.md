# FactoryPulse｜工业设备健康监测与维护辅助决策系统

这是一个可以在 **Windows 电脑上运行的桌面软件 MVP（最小可用版本）**。你不需要先连接工厂设备：下载我们准备好的 Excel 测试文件，导入后就能查看设备数据、模拟风险和维护方案，还能在软件的“开发者设置”中填写自己的 AI API。

> **请先了解：** 本项目目前用于课程、竞赛和功能演示。Excel 中的设备、维修、订单、风险值均为**模拟数据**。风险分数不是训练好的 AI 模型预测，维护成本也不是工厂真实收益。不要用它做实际安全决策。

## 🌐 网页版：通过 GitHub Actions 自动发布到 GitHub Pages

**预期网址：** https://observl.github.io/FactoryPulse/

1. 打开仓库的 [Actions](https://github.com/Observl/FactoryPulse/actions)。
2. 找到 **Publish FactoryPulse Web Demo** 工作流，确认最新一次运行结果为绿色成功。
3. 打开 [Settings → Pages](https://github.com/Observl/FactoryPulse/settings/pages)，在 **Build and deployment** 下查看是否已选择 **GitHub Actions**。若未生效，请手动选择 GitHub Actions，并重新运行工作流。
4. 工作流成功且 Pages 状态显示已发布后，再访问上述网址。首次发布可能需要等待数分钟。
5. 如果仓库是私有的，需确认当前 GitHub 账户方案允许从私有仓库发布 Pages。

网页版**无需安装 Python、Node.js，也无需运行 FastAPI**。首次访问会载入 12 台**内置模拟设备**；之后可在“设备管理”上传此项目的 **FactoryPulse_完整功能测试数据与字段字典.xlsx**（见本聊天提供的下载文件），网页会本地解析并替换演示数据。请按下面的 Excel 导入、风险分析、维护策略与 CSV 下载流程测试。

**网页版特别说明：**

- GitHub Pages 仅托管静态页面；Excel 在**浏览器本地**读取，维护策略计算也在本地完成。
- 上传数据保存在当前浏览器的 localStorage 中。更换浏览器或清除网站数据后需重新导入；浏览器空间不足时不能持久化。
- 网页版禁用 AI API Key 保存及 Factory Copilot 的第三方 AI 调用，以免把密钥暴露在公开网页中。本地桌面版仍支持后端 AI API 设置。
- 此网页只用于演示，不要上传公司的机密或真实生产数据，也不要将模拟风险结果用于生产决策。
- “GitHub Actions 发布成功”与“网页能正常使用”是两项独立验收：还需在浏览器手动导入 Excel、比较方案并导出 CSV。

---

## 一、目前能做什么？

| 页面 | 具体可以做的事 | 状态 |
|---|---|---|
| 设备总览 | 查看设备总数、模拟风险分布、运行指标 | ✅ 可用 |
| 设备管理 | 选择并导入 Excel；数据保存到本机 SQLite | ✅ 可用 |
| 风险预测 | 查看 Excel 预置的演示风险评分 | 🟡 演示模式，尚未接入训练模型 |
| 异常解释 | 查看风险评分及温度、转速等监测证据 | 🟡 尚无模型特征归因 |
| 维护策略 | 对比固定顺序、风险阈值、贪心优化三种方法，模拟预算和停机约束 | ✅ 演示算法可用 |
| 维护计划 | 查看仿真得到的候选维修任务，以及维修人员、维护记录、订单预览 | 🟡 尚无正式排程 |
| Factory Copilot | 配置 AI API 后，对设备数量、模拟风险汇总提问 | ✅ 仅支持**汇总数据问答** |
| 开发者设置 | 填写 AI 服务商、接口地址、模型、密钥并测试连接 | ✅ 可用 |

项目代码已上传到 [GitHub 仓库](https://github.com/Observl/FactoryPulse)，后续任务在 [Issues](https://github.com/Observl/FactoryPulse/issues)。

## 二、开始之前，安装这两个软件

**软件一：Node.js（推荐 22 LTS）**

下载：https://nodejs.org/

**软件二：Python（推荐 3.12）**

下载：https://www.python.org/downloads/

安装好后，打开 PowerShell，依次输入：

```powershell
node -v
npm -v
py -3.12 --version
```

能显示版本号就表示装好了。如果第三条提示找不到 Python，请检查 Python 3.12 是否正确安装，也可以用 `python --version` 检查。

建议用 VS Code 或 Cursor 打开项目文件夹。

## 三、把项目下载到电脑

方法 A（不懂 Git 也可以）：

1. 打开 https://github.com/Observl/FactoryPulse
2. 点击绿色 **Code** 按钮。
3. 选择 **Download ZIP**。
4. 解压到电脑，例如 `D:\FactoryPulse`。
5. 用 VS Code 或 Cursor 打开这个文件夹。

方法 B（安装 Git 后）：

```powershell
git clone https://github.com/Observl/FactoryPulse.git
cd FactoryPulse
```

下面所有命令均在 **FactoryPulse 项目根目录**运行，除非另有说明。

## 四、运行软件：打开两个终端

在 VS Code 中点击菜单“终端 → 新建终端”。建议创建两个 PowerShell 终端。

### 终端 1：启动数据服务（Python）

复制并依次运行：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

出现 `Uvicorn running on http://127.0.0.1:8000` 表示后台已启动。

浏览器打开 http://127.0.0.1:8000/api/health ，如果看到 `"status":"ok"` 就通过第一项测试。

**注意：** 后端运行时不要关闭此终端。数据默认存在当前电脑用户目录 `~/.factorypulse/factorypulse.sqlite3`。

### 终端 2：打开软件窗口（Node.js / Electron）

在项目根目录运行：

```powershell
npm install
npm run dev
```

稍等，应该会弹出 **FactoryPulse** 桌面窗口。如果没有弹窗，也可以在浏览器打开 http://127.0.0.1:5173 （单独浏览器运行可用 `npm run web`）。

此时左侧应该能看到“设备总览”“设备管理”“风险预测”“异常解释”“维护策略”“维护计划”“Factory Copilot”和底部的“开发者设置”。

---

## 五、直接照做：MVP 完整测试流程

### 测试 1：导入给你的 Excel

1. 在聊天记录里下载 **FactoryPulse_完整功能测试数据与字段字典.xlsx**。
2. 打开软件，点击左侧 **设备管理**。
3. 点击 **选择测试Excel文件**。
4. 选中该 `.xlsx` 文件，等待提示“成功导入”。
5. 导入时系统会检查 **8 张业务工作表**、必填列、设备编号关联及风险分数范围；另两张“使用说明”和“字段字典”用于阅读，不参与存储。

**预期结果：** 设备总数是 **12 台**；运行监测约 **144 条**；维护历史约 **36 条**；生产订单约 **30 条**。导入成功后界面会刷新，关闭软件再启动，SQLite 中的数据仍会存在。

### 测试 2：查看设备总览和风险

1. 点击 **设备总览**。
2. 看上方的设备数量和高风险设备统计。
3. 看中部柱状图及下方设备明细表。
4. 点击 **风险预测**，查看各设备的演示风险分数。
5. 点击 **异常解释**，核对设备温度、转速与风险值。

**预期结果：** 设备能正常展示；柱状图和表格有数据；页面明确注明“模拟风险评分，非真实模型预测”。

### 测试 3：运行三种维护策略

1. 点击左侧 **维护策略**。
2. 在“情景”下拉框选择“基准方案”等 Excel 预置情景。
3. 选择“收益比贪心优化”。
4. 点击 **计算并比较三种策略**。
5. 核对对照表里是否有“固定顺序”“风险阈值优先”“收益比贪心”三行。
6. 检查维护金额、工时和入选任务是否合理。
7. 点击 **导出维护计划 CSV**，用 Excel 打开导出文件。
8. 切换不同情景重复测试。

**预期结果：** 每项方案的维护金额不得超过情景预算，工时不得超过情景停机上限；不同策略通常会得到不同任务和成本。

**计算方法特别说明：** 为了可重复演示，暂时假定一次维护使对应演示风险下降 **60%**，再以模拟故障损失计算示意收益。所谓“优化”使用贪心排序，不保证找到全局最优方案，不可当作实际生产决策结论。

### 测试 4：检查维修计划与订单

1. 先执行测试 3，让软件生成候选维护计划。
2. 点击 **维护计划**。
3. 查看刚才的候选任务，以及下方维修历史、维修人员、生产订单预览。

**预期结果：** 页面能看到导入的不同业务数据。目前尚未自动安排具体人员的日历时间段，也不会自动改变订单交期。

### 测试 5：设置 AI API（可选）

> 没有 API Key 也可以完成前四项测试。AI API 不是软件启动的前提。

1. 点击左侧最底部 **开发者设置**。
2. 选择服务商，例如 DeepSeek、通义千问、OpenAI 或自定义。
3. 按服务商的官方文档填写 **API Base URL** 和 **模型名称**。
4. 在 **API Key** 中输入自己的密钥。
5. 点击 **保存配置**，再点击 **测试连接**。
6. 成功后进入 **Factory Copilot**，输入“目前设备风险概况如何？”。
7. 点击提问按钮，看是否返回基于**设备总数、演示风险统计和记录数量**的中文解释。

**预期结果：** 配置正确、网络和账户额度正常时，可完成测试及问答。API 功能可能产生第三方调用费用。

**数据隐私与密钥：** 密钥不会提交到 GitHub，也不会写入 Excel；当前版本保存在后端进程内存中，重启后需重新填写，也可用环境变量 `FACTORYPULSE_AI_API_KEY` 设置。Copilot 仅向 AI 服务商发送汇总信息和你输入的问题，不会自动上传整本 Excel。

### 测试 6：异常输入和健壮性检查

- 上传 `.txt` 文件：应被拒绝。
- 上传缺少必要业务工作表的 Excel：应提示具体缺失表。
- 修改演示风险分数为超出 `0～1` 的值：应提示校验失败。
- 停止 Python 服务后操作设备页面：应显示连接错误。
- 不填 API Key 就测试连接：应提示需要配置。
- 尝试填写本地或内网 API 地址：应该被拒绝。

## 六、运行自动化测试

项目已配置 GitHub Actions 自动检查前端构建和后端测试，也可以在本机手动检查：

```powershell
npm run build
.venv\Scripts\python.exe -m pip install pytest
.venv\Scripts\python.exe -m pytest -q
```

检查最新结果：[GitHub Actions](https://github.com/Observl/FactoryPulse/actions)。

**注意：** 自动化测试配置已经上传仓库，但不意味着已经验证全部通过；以 Actions 页面实际结果为准。

## 七、看懂 Excel 需要什么字段

| 数据表 | 主要字段 | 用途 |
|---|---|---|
| 设备档案 | `equipment_id`、`equipment_name`、`equipment_type`、`status` | 设备管理和跨表关联 |
| 运行监测 | `reading_id`、`equipment_id`、`timestamp`、温度、转速、扭矩、刀具使用时间 | 趋势和风险特征 |
| 维护参数 | `equipment_id`、检查/维修成本、时间、人数、假设故障损失 | 维护策略计算 |
| 维护历史 | `maintenance_id`、`equipment_id` | 历史记录 |
| 维修人员 | `staff_id`、`available_hours` | 人员可用性数据预览 |
| 生产订单 | `order_id`、`equipment_id` | 订单数据预览 |
| 策略情景 | `scenario_id`、`maintenance_budget_cny`、`risk_threshold`、`available_staff_count`、`max_downtime_h` | 预算/阈值/人员/停机约束 |
| 演示风险 | `equipment_id`、`risk_score` | UI 演示风险，数值0～1 |

## 八、遇到问题怎么办？

| 问题 | 检查方法 |
|---|---|
| `npm` 命令不存在 | 重新安装 Node.js LTS 并重启终端 |
| `py -3.12` 不可用 | 检查 Python 3.12 的安装；必要时改用 `python` |
| 页面提示后端未启动 | 查看第一个终端的报错，确认本地8000端口没有被占用 |
| Excel 导入报错 | 先用提供的原始文件测试，不要改工作表名称、必填列或设备编号 |
| 安装 Python 依赖失败 | 使用较新的 pip：`.venv\Scripts\python.exe -m pip install --upgrade pip` |
| AI API 连接失败 | 检查是否有网络、密钥是否正确、模型是否存在、Base URL 是否为公开 HTTPS 服务 |
| Electron 窗口不弹出 | 先运行 `npm run web`，用浏览器排除前端问题 |

## 九、项目现阶段的限制

这是竞赛原型，**还不是工业生产系统**。以下功能需要后续版本完善：AI4I 机器学习故障预测、特征归因解释、基于真实模型的维护收益评价、考虑订单冲突和人员班次的排程优化、API密钥的安全持久存储、Windows 安装程序及无依赖电脑的安装验证。

建议按“先用测试Excel跑通全流程 → 再替换风险评分为训练模型输出 → 最后强化优化与正式打包”的顺序迭代。

### GitHub Pages 发布检查

仓库 Settings → Pages → Build and deployment → Source 必须选择 **GitHub Actions**。设置完成后，向 main 提交代码会自动触发 `Publish FactoryPulse Web Demo`；请在 Actions 中确认 `build` 和 `deploy` 均成功，再打开 https://observl.github.io/FactoryPulse/ 。如遇错误，优先检查 `Verify Pages is enabled` 和 `Publish` 步骤的日志。
