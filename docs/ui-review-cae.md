# 界面优化空间与 CAE 面试适配评估

> 对象：`dafeiyu_gui/`（大肥鱼控制台，PyQt5 桌面端）
> 目的：① 找出界面可优化点；② 判断它作为 Qt 作品去面 CAE 软件公司的成色，以及怎么补。
> 说明：本文所有结论都基于实际读码 + 真机渲染截图 + 运行时测量，未改动项目任何代码。

---

## 0. 结论摘要

1. **界面底子不差，属于"脚本包装工具"里的中上水平**：有设计 token、双主题、卡片系统、脱敏、单实例、异常兜底、53 个测试全绿。问题以**细节和工程结构**为主，不是审美崩坏。
2. **真正的短板不在"好不好看"，而在"像不像一个专业桌面软件"**：没有菜单栏/工具栏/停靠面板/Model-View/命令撤销，这些恰好是 CAE 界面的骨架，也是面试官判断"你能不能做 CAE 界面"的直接依据。
3. **作为 CAE 作品，目前只证明了"会 Qt 工具开发"**，还证明不了"能做 CAE 前后处理界面"。要补 3 件东西：Model/View、Dock 布局、3D 视口（VTK）。其中 Model/View 是性价比最高的第一块砖。
4. **最强的一击不是打磨这个界面，而是加一个"仿真垂直切片"**（模型树 → 参数面板 → 3D 网格 → 求解任务 → 云图/曲线），哪怕很小。讲述逻辑：*先用 Python/PyQt 快速验证交互，再用 C++/Qt6 落地*——这对 CAE 公司是极好的叙事。
5. 顺手还挖到 3 个**真实小 bug**（下方 P0），都很好修，修完正好是面试里"我自己的项目我能挑出毛病并改掉"的素材。

---

## 1. 现状快照

| 项 | 事实 |
|---|---|
| 技术栈 | Python 3.10+ / **PyQt5 5.15.10**（`requirements-gui.txt` 锁 `<6`）/ QtWidgets（无 QML）/ Fusion 风格 / 手写 QSS 主题 |
| 规模 | 界面层约 **2.9k 行**（`main_window` 940、`theme` 407、`widgets` 396、`settings_page` 304、`overview` 287、`dialogs` 229、`app` 183、`help_page` 94、`runner_bridge` 48）；后端约 1.1k 行 |
| 页面 | 总览（状态 6 卡 + 后台链接 + 操作区 + 进度 + 日志）、配置（16 字段表单）、帮助（富文本） |
| 主题 | `theme.py` 两套 24 色 token + `Template` 拼 QSS，`setProperty` + `unpolish/polish` 动态换肤 |
| 线程 | `threading.Thread` 读子进程输出 → `pyqtSignal` 跨线程回主线程（`runner.py` / `runner_bridge.py`） |
| 打包 | PyInstaller onefile + `--hidden-import PyQt5.QtSvg` + 图标由 SVG 生成（`build_gui_exe.ps1`） |
| 测试 | 实测 **53 个用例 3.5s 全过**，含 offscreen UI 冒烟测试（还专门处理了 `QT_QPA_FONTDIR`） |

**可以拿去讲的技术点（都是真材实料）**：单实例 `QLockFile`、`sys.excepthook` 兜底弹窗、几何/主题/页面 `QSettings` 持久化、关闭运行中操作的二次确认、密码字段脱敏（表单 + 日志双层）、SSH 主机密钥必须人工输入 `YES`、破坏性对话框默认按钮是"取消"、幂等重跑提示。

---

## 2. 界面优化空间

按"改动收益 / 成本"排序。P0 = 明显缺陷或观感损失，P1 = 专业度提升，P2 = 长期结构。

### 2.1 P0：真实缺陷（建议先修，修完就是面试谈资）

> 本节 4 项已在「档 1」全部修复，实施记录见 §8；下面是当时的问题描述，保留作为评审依据。

| # | 位置 | 问题 | 证据 | 改法 |
|---|---|---|---|---|
| 1 | `overview.py:260-272` | **操作完成的提示文案永远看不到**：`finish_operation()` 先把结果写进 `_progress_label`，下一行 `self.progress_panel.hide()` 就把整个面板藏了 | 实测 `PROGRESS_PANEL_VISIBLE_AFTER_FINISH=False`，而 `PROGRESS_LABEL_TEXT='部署 / 更新完成，QQ 当前在线。'` | 要么保留一个 3 秒的"完成摘要条"，要么把文案交给 `Banner`/状态栏；顺手把 `finish_operation` 拆成 `show_result()` + `collapse()` |
| 2 | `main_window.py:739-760` | **停止服务后"最近检查"时间不更新**：卡片已变"已停止"，但 `_status_hint` 还停在旧时间 | 实测：卡片 `已停止`，hint 仍是 `最近检查：09:35:10`，`status_report.checked_at` 已是当前时间 | `mark_stopped()` 同步更新 hint，或直接构造 `StatusReport` 走 `apply_report()` 统一入口 |
| 3 | `widgets.py:74,95` | **状态卡副标题恒定被裁**：卡片 `setFixedHeight(84)`，副标题 `setFixedHeight(16)`，而 8.5pt 字体实测行高 **17px** | 实测 `detail_label_h=16`、`text_px_h=17`；长文本 391px 塞进 274px 且**没有省略号**（只有 tooltip） | 去掉 `setFixedHeight`，改用 `QFontMetrics.elidedText` + `resizeEvent` 重算；或让 QLabel 自动 `wordWrap` 两行 |
| 4 | `main_window.py:95` + `overview.py` 整体无滚动容器 | **1080p + 150% 缩放的笔记本放不下**：最小尺寸 `980×760` 是逻辑像素，1920×1080@150% 只剩 **720 逻辑高** < 760 | 算术即可确认；且总览页直接 `QVBoxLayout`，没有 `QScrollArea`（只有配置页有） | 总览也包 `QScrollArea`（`setWidgetResizable(True)`），最小尺寸降到 ~`900×620`，或按 `availableGeometry` 动态算 |

> 这三个 bug + 高 DPI 那个，足够在面试里讲一段"我后来做了可用性回归，发现…"。

### 2.2 P1：信息架构与布局

1. **双主标题打架**：顶栏写死 `AstrBot + NapCat`（`main_window.py:176-183`），而配置页/帮助页自己又有 `PageTitle`（`settings_page.py:55`、`help_page.py:71`），视觉上出现两个 H1。侧栏已经有大肥鱼品牌，顶栏应改成**当前页面名 + 上下文操作**。
2. **大屏失控**：1600 宽时主按钮被拉到 1100px，日志区变成巨大空白。缺一个 `max-width` 内容容器（~1080–1200）+ 居中。CAE 软件也一样：参数面板不会被拉伸到满屏。
3. **日志区占比过高且空置**：无内容时也占约 40% 高度（`overview.py:158-160`，`stretch=1`）。改成 `QSplitter`（可拖）+ 默认折叠到 ~160px + 有内容时自动展开。
4. **运行时布局跳动**：`begin_operation()` 直接 `actions_card.hide()`（`overview.py:228`），操作卡和进度面板高度不同，下方日志整块位移。改成**同高占位**或把操作区改成禁用态而不是隐藏。
5. **状态区信息密度低**：6 张固定 84px 卡片只放"标签 + 一个值 + 一行小字"，独占 ~200px。可压缩成一行 chip 条，或换成两列表格式摘要（也顺便向 CAE 的"结果摘要面板"靠拢）。
6. **散落元素**：`最近检查`（`overview.py:57`）、`6185 / 6099 · 安全组需放行`（`overview.py:73`）、`后台地址` 行，都浮在卡片和操作卡之间，没有归属容器。端口提示属于运维知识，应该进帮助页或 tooltip。
7. **配置页 16 字段平铺**：每字段一行 hint（8.5pt），要滚约 3 屏；**没有必填标识、没有搜索、没有分组折叠、没有"已修改"标记**。空密码字段的 placeholder 是"已填写时显示为圆点"（`settings_page.py:136`），对空字段来说语义是反的，容易误读。
8. **两套"显示密码"机制并存**：全局 `显示敏感字段`（`settings_page.py:70`）+ 每行 `显示` 按钮（`widgets.py:366`），`load_document` 时全局勾选被重置、行内 toggle 保留，状态容易互相打脸。留一个就好。

### 2.3 P1：视觉与一致性

9. **内联样式破坏设计系统**：`main_window.py:132/161/178` 用 `setStyleSheet("font-size: 13pt;")` 覆盖 QSS，而 `theme.py` 里 `AppTitle` 14pt / `PageTitle` 15pt 又另有一套 → 同一层级字号三处定义。
10. **QSS 全局锁字号 = 无障碍失效**：`theme.py:62-66` 给 `QWidget` 写死 `font-size: 9.5pt`。实测把 `QApplication` 字体调到 13pt，界面文字**几乎没变**（全被 QSS 的 pt 覆盖，只有没写 font-size 的控件变大），状态卡副标题本来就因 16px 固定高而裁切，大字号下更明显（截图 `10_layout_bigfont.png`）。桌面软件应尊重系统字体缩放：正文用 `pt` 但允许应用字体生效，或干脆做一个"界面缩放"设置项。
11. **日志区字体硬编码**：`widgets.py:298` `setFont(QFont("Consolas", 9))` 覆盖了 QSS 里精心写的 `"Cascadia Mono", "Consolas", "Microsoft YaHei UI"` 回退链 → 中文落到默认字体，和界面其余文字不统一。
12. **按钮层级不清**：7 个按钮只有 1 个 primary，`停止服务…`（破坏性）和 `刷新状态` 同款外观，`同步 Token`/`同步密码兜底`（低频维护）也和常用操作同级。建议：主操作 + 次级 + "更多"菜单；停止给 danger 描边。
13. **小字偏多**：`CardHint`/`CardDetail`/`FieldHint`/`InlineNote`/`FooterHint` 全是 8.5pt，100% 缩放下偏小；正文建议 9.5–10pt、辅助 9pt。
14. **零图标**：侧栏、按钮、状态卡全是纯文字。CAE 软件几乎都是"图标 + 文字"的工具栏形态；哪怕只给 7 个操作配一套单色 SVG 也会立刻"专业"很多。
15. **浅色主题里的深色日志**：可以接受（终端隐喻），但日志块与浅色卡片之间没有分隔/标题层级，观感上像贴了一块黑胶布。加个 8px 圆角 + 顶部细描边 + "终端"标签即可。

### 2.4 P2：Qt 工程与可维护性（面试深挖点）

16. **手写 widget 拼装，零 Model/View**：全项目 grep 不到 `QAbstractItemModel`/`QTreeView`/`QTableView`/`QSortFilterProxyModel`/delegate。CAE 的模型树、参数表、结果表全靠这套，这是**最大缺口**（见 §4）。
17. **无 QAction / QMenuBar / QToolBar / QDockWidget / QUndoStack**：全项目只有 2 个 `QShortcut`（F5、Ctrl+Q；`main_window.py:227-230`），连 Ctrl+S 都没有。桌面软件的"命令系统"完全缺失，启用状态、快捷键、图标都得手工在每个按钮上同步 → 已经出现 `_update_actions()` 里一堆手工布尔。
18. **状态分散**：`_busy`、`_finishing`、`_closing` + `overview._busy` + `settings_page._busy` 五处布尔同步；改一个状态要记得通知 3 个地方。建议单一 `AppState` + 信号。
19. **MainWindow 940 行什么都干**：读文件、校验、建对话框、拼子进程、发日志、写状态。`commands.ACTIONS`（`backend/commands.py`）已经有 `ActionSpec` 雏形，可以顺势扩成 `QAction` 工厂 + Controller 分层——这是"我把脚本包装器重构成可扩展桌面应用"的好故事。
20. **死代码**：`StatusBoard.mark_started()`（`widgets.py:199`）、`SettingsPage.focus_field()`（296）、`discard_unsaved()`（302）、`RunnerBridge.clear_finished()`（44）、`PasswordLineEdit.setEnabled` 空覆写（391）。面试官真会点开看。
21. **主题实现方式**：`string.Template` 拼 QSS 可行，但没有热加载、没有 QSS 变量校验；`QWidget {}` 这种全局选择器还会顺带影响 `QMessageBox`/`QFileDialog` 的原生控件外观（有些弹窗看着"像网页"）。
22. **PyQt5 的许可证是硬伤**：PyQt5 是 **GPLv3 / 商业授权**，闭源商用要么开源要么买 license；**PySide6 是 LGPLv3**，动态链接即可闭源商用。CAE 公司卖的是商业软件，这条一定要主动说（见 §6）。同时 `requirements-gui.txt` 还锁 `<6`。

---

## 3. 高 DPI / 无障碍 / 跨平台小结

| 项 | 现状 | 风险 |
|---|---|---|
| 高 DPI | 已设 `AA_EnableHighDpiScaling` / `AA_UseHighDpiPixmaps`（`app.py:113-116`），Qt6 下这两项语义变了/移除 | 像素常量（84/16/208/980×760）与 `pt` 字号混用，缩放不一致 |
| 系统字体缩放 | 被 QSS `9.5pt` 覆盖 | 大字号用户得不到收益，反而裁切 |
| 字体回退 | QSS 只写了 `Microsoft YaHei UI / Segoe UI` | Linux/macOS 上无中文回退链，CAE 的 Linux 端会踩 |
| 无障碍 | 无 `setAccessibleName`、无 tab order、无 mnemonic（按钮文本无 `&`）、状态只靠颜色 + 文字 | 可接受但不算加分 |
| i18n | 全中文硬编码，`tr()` 零使用 | CAE 产品普遍要中英双语 |
| 单色图标/主题 | 无 `QIcon` 体系（除窗标） | 深色/浅色切换时图标适配会成新问题 |

---

## 4. 面向 CAE 岗位的差距分析

### 4.1 CAE 前后处理界面的"标准骨架"

国内外 CAE 前处理（ANSYS Mechanical、Abaqus/CAE、HyperMesh、COMSOL、PrePoMax、FastCAE/Salome…）界面高度趋同：

```
┌──────────────────────────────────────────────────────────┐
│ 菜单栏  文件 编辑 视图 模型 网格 分析 结果 工具 帮助      │
│ 工具栏  [导入][几何][网格][材料][边界][求解][后处理]      │
├──────────┬───────────────────────────────┬───────────────┤
│ 模型树   │        3D 视口（VTK/OpenGL）  │  属性面板     │
│ 几何     │  网格 / 变形 / 云图 / 拾取    │  (动态表单)   │
│ 网格     │                               │               │
│ 材料     ├───────────────────────────────┤  单位/校验    │
│ 边界     │  消息 / 求解日志 / 命令回显   │               │
│ 求解     │                               │               │
│ 结果     │                               │               │
├──────────┴───────────────────────────────┴───────────────┤
│ 状态栏：求解器状态 · 单元数/节点数 · 内存 · 进度          │
└──────────────────────────────────────────────────────────┘
```

要点：**模型树（QTreeView + QAbstractItemModel）**、**属性编辑器（动态表单/delegate）**、**中央 3D 视口（VTK）**、**消息/命令区**、**作业监控（进度/取消/日志）**、**菜单+工具栏+右键菜单（QAction）**、**撤销栈**、**单位与参数校验**。

> 旁证：湖南大学一篇基于 Qt 做车身有限元流程化系统的硕士论文，明确写的就是"菜单、模型树、视图窗口和操作面板"四大分区 + 信号槽联动（[节点文献](http://cnki.cgl.org.cn/KCMS/detail/detail.aspx?filename=1024449586.nh&dbcode=CMFD&dbname=CMFD2025)）；FastCAE 的 FITK 也专门有 `GUIWidget` 模块提供"树控件 / 属性编辑器 / 拾取数据"（[APPFlow/GUIWidget](https://gitcode.com/gcw_sJJxwlUh/APPFlow/tree/master/GUIWidget)）。这说明这不是我一家之言，而是行业共识的骨架。

### 4.2 本项目 vs 骨架

| 能力 | CAE 要求 | 本项目 | 差距 |
|---|---|---|---|
| 信号槽 / 事件 | 必备 | ✅ 大量使用，跨线程桥接规范 | — |
| QSS / 主题 | 常见 | ✅ token 化双主题 | 缺缩放与原生对话框隔离 |
| 布局管理 | 必备 | ✅ 手写 QVBox/QHBox/QGrid/QForm | 缺 splitter/dock/滚动容器 |
| **Model/View** | **核心** | ❌ 零 | **最大缺口** |
| **3D 视口** | **核心** | ❌ 零 | 需 VTK/OpenGL |
| **Dock / 菜单 / 工具栏 / 命令** | **核心** | ❌ 零（只有 2 个 QShortcut） | 需 QAction + QDockWidget |
| 长任务 / 进度 / 取消 | 必备 | ✅ 有（progress + step chips + cancel + taskkill /T） | 缺作业历史 |
| 多线程 | 必备 | ✅ threading + 信号 | 缺 QThread/线程池范式（可讲） |
| 跨平台 | Windows/Linux | ❌ 只有 Windows（PowerShell、字体、路径） | 需抽象层 |
| 构建 | CMake | ❌ 只有 PyInstaller | C++ 岗必补 |
| 安全 / 脱敏 | 加分 | ✅✅ 双层脱敏 + 绝不显示 QQ 密码 | 亮点 |
| 测试 | 加分 | ✅✅ 53 用例 + offscreen 冒烟 | 亮点 |
| 领域（网格/FEA/结果格式） | 看岗位 | ❌ 零 | 需垂直切片 |

### 4.3 岗位映射：同一份项目怎么讲（回答"不一定是前端岗"）

| 目标岗位 | 这个项目的分量 | 该重点讲什么 | 该补什么 |
|---|---|---|---|
| **CAE 前后处理 GUI（C++/Qt）** | 30–40% | 线程模型、脱敏、长任务 UX、QSS 系统 | Model/View、Dock、VTK、C++ 复刻 |
| **CAE 平台/工具链/自动化（Python 为主）** | 60–70% | subprocess 编排、幂等、错误处理、打包、测试、安全边界 | 插件化、任务队列、REST/gRPC 对接 |
| **求解器/算法岗** | 次要证据 | **只讲工程素养**（测试/打包/错误处理/文档），别展开 UI | 主力证据要是数值/并行/性能 |
| **测试/QA/DevOps** | 70%+ | offscreen 冒烟测试、幂等验证、`--dry-run`、日志脱敏 | CI、覆盖率、性能基线 |

> 现实提醒：CAE 界面岗的 JD 几乎都写 C++11/14/17 + Qt + CMake + VTK/OpenGL + Windows/Linux 跨平台。
> 参考：[昆仑数模 C++ 开发（西安）](http://jy.xust.edu.cn/detail/job?id=2726259)、[凌云智擎 QT 工程师](https://24365.beijing.smartedu.cn/frontpage/bjbys/html/bilateralchosefairOrderForm.html?recruitmentId=bcf16f74d3ea46e9ba1c66a54d6381a3)、[Cadence Software Engineer II](https://www.naukri.com/job-listings-software-engineer-ii-cadence-pune-3-7-years-080926502714#1)、[中物院软件中心前后处理方向](https://www.chaojijianli.com/xiaozhao/cae-cn-simulation-center-2026-campus-18542-8cacd3/#1)。
> 所以：**Python 项目可以拿，但要明确"我是用 Python 验证交互，Qt 概念可直接迁 C++"，并且手上最好真有一个 C++/Qt6 小样。**

---

## 5. 改造路线（三档，按投入产出排序）

### 档 1：界面打磨（0.5–1 天，先把"不专业感"清零）

按顺序做，每项都能独立提交、独立讲：

1. 修 §2.1 的三个 bug（完成文案、停止后时间戳、卡片副标题裁切）。
2. 总览页套 `QScrollArea` + 最小尺寸降到 `900×620`，并加 `max-width` 内容容器。
3. 删掉写死的 `AstrBot + NapCat` 顶栏标题，统一"当前页面名 + 副标题 + 右侧上下文"。
4. 日志区换成 `QSplitter`，默认 160px；`清空/复制/保存` 收到一个 `⋮` 菜单里。
5. 按钮分级：`一键部署` primary / `刷新状态·启动·停止` 次级 / `同步 Token·同步密码·SSH 终端` 进"更多"；停止加 danger 描边。
6. 配置页：加**必填星号**、字段级"已修改"标记、分组折叠、`Ctrl+S` 保存；删掉一套 reveal 机制；修 placeholder 文案。
7. 去掉所有 `setStyleSheet("font-size: ...")` 内联样式，字号归 QSS；`LogView` 去掉 `setFont` 硬编码。
8. 状态卡副标题改 `elidedText`（约 10 行代码）+ tooltip 保留全文。
9. 侧栏 + 7 个操作配单色 SVG 图标（`QIcon` + `QIcon.fromTheme` 兜底）。

> 完成后的说法：*"我做了一轮可用性回归：修了状态反馈丢失、时间戳不同步、高 DPI 裁切，并把设计 token 收敛进 QSS。"*

### 档 2：Qt 架构升级（5–8 天，**性价比最高**）

目标：把"脚本包装器"变成"有桌面软件骨架的应用"。

1. **换 PySide6**（LGPL）：`from PyQt5.QtX import` → `from PySide6.QtX import` 为主，`exec_()`→`exec()`，`pyqtSignal`→`Signal`；补 `requirements` 与打包脚本。**这一步本身就是面试话题（许可证）**。
2. **引入 Model/View**：
   - `KeyFieldModel(QAbstractTableModel)`：16 个字段 + 值 + 必填 + 校验状态；配 `QSortFilterProxyModel` 做搜索/只看必填。
   - `TaskTreeModel(QAbstractItemModel)`：把"部署阶段"改成树（部署 → 上传/镜像/服务/守护/配置/检查），带状态图标与进度列——这就是 CAE 模型树的雏形。
   - `QStyledItemDelegate`：密码列显示圆点、错误行红底、必填列灰字。
3. **Dock 布局**：`QMainWindow` + `QDockWidget`：左"任务/步骤树"、下"运行日志"、右"字段/属性"、中央"概览/输出"；用 `QSettings` 保存 `saveState()/saveGeometry()`。
4. **命令系统**：`QAction` 注册表（由 `commands.ActionSpec` 生成）+ `QMenuBar` + `QToolBar` + 右键菜单；启用状态由模型驱动，删掉 `_update_actions()` 的手工布尔。
5. **撤销栈**：配置编辑用 `QUndoStack`（改字段、恢复默认），这是 CAE 参数编辑的标准体验。
6. **长任务节流**：日志按 50–80ms 批量 flush（现在逐行 `QTextCursor.insertText` 实测 0.03ms/行、连续 5000 行 0.16s，**够用**，但高吞吐场景批量更稳）；顺便把 `_current_output` 上限从 10 万行降到 2 万 + 落盘轮转。
7. **i18n 兜底**：至少把界面串收进 `tr()`，给英文 `.qm` 留口子。
8. **状态集中**：`AppState` 单例 + `stateChanged` 信号，替掉 5 个 `_busy`。

> 完成后的说法：*"我用 Model/View 把参数表和任务树数据化，用 QAction 统一命令与启用状态，用 QUndoStack 做可撤销编辑，用 Dock 做了可保存的布局——这套就是 CAE 界面的骨架。"*

### 档 3：加一个 CAE 垂直切片（10–15 天，**投 CAE 必做**）

不要贪大，做一个"悬臂梁/板壳模态分析"最小闭环，重点是**交互链路完整**而不是求解精度：

| 模块 | 实现 | 面试讲点 |
|---|---|---|
| 模型树 | 几何/网格/材料/边界/求解/结果（`QAbstractItemModel`） | 数据驱动、懒加载、右键菜单 |
| 属性面板 | 选中节点 → 动态表单（`QFormLayout`/delegate） | 单位、范围校验、联动 |
| 3D 视口 | `pyvistaqt.QtInteractor`（VTK）或 `QOpenGLWidget` | 网格显示、变形放大、应力云图 colormap、**拾取节点出读数** |
| 求解 | numpy/scipy 小型有限元（梁单元即可），`QThread` 跑 | 线程/进度/取消、UI 不卡 |
| 结果 | `QAbstractTableModel` 结果表 + `pyqtgraph` 曲线 | 大数据 tablemodel、导出 CSV |
| 作业监控 | 任务列表：排队/运行/成功/失败 + 日志 + 耗时 | 对齐 CAE job monitor |
| 报告 | 一键导出 HTML/PNG | 工程交付感 |

> 如果时间允许再走一步：用 **Qt6 + CMake + VTK C++** 复刻这个骨架的 30%（模型树 + dock + 视口 + 一个求解按钮）。**Python 原型 + C++ 落地**的组合，比任何一个单独版本都更能打动 CAE 面试官。

---

## 6. 面试话术

### 6.1 三分钟版（照着说就行）

1. **背景与边界**：*"这是给一条真实部署链路做的本地 GUI。命令行脚本是唯一权威，GUI 只做编排、状态呈现和危险操作拦截——我刻意没有把业务逻辑搬进界面，这样 CLI 用户不受影响。"*（体现工程判断）
2. **技术点**：*"QtWidgets + QSS 双主题；子进程输出用后台线程读、通过信号回主线程，保证 UI 不卡；主机密钥变化必须人工输入 YES，所以我把 stdin 打通了；密码和 API Key 做表单与日志双层脱敏；单实例锁、异常兜底、几何与主题持久化都做了。"*
3. **取舍**：*"没用 QProcess，是因为要隐藏控制台并稳定写 stdin；状态故意不自动轮询，因为 NapCat 接口每分钟限 3 次；停止操作有 dry-run 预览和二次确认。"*（每个"为什么不"都是加分项）
4. **反思**（主动揭短，最容易被记住）：*"现在最大问题是手写 widget 导致状态分散、没有 Model/View，也不支持大字号。如果重做我会：换 PySide6（LGPL）、把参数和任务做成 model、用 QAction 统一命令、把 dock 布局持久化。"*
5. **钩子**：*"基于这个教训，我另做了个 CAE 前处理的小 demo：模型树 + 属性面板 + VTK 视口 + 求解任务，用来说明这套骨架能迁到 C++/Qt6。"*

### 6.2 高频追问与答法

| 追问 | 回答要点 |
|---|---|
| 为什么 Python 不用 C++？ | 本地工具、迭代速度优先；Qt 概念一一对应（信号槽/布局/模型视图）；C++ 迁移成本在类型、内存、构建，不在 Qt 用法。**然后立刻展示 C++/Qt6 小样** |
| PyQt5 能用在商业产品吗？ | 不能直接：PyQt5 是 GPLv3 或商业授权；**PySide6 是 LGPLv3**，动态链接可闭源商用。这是我会首先改的依赖 |
| 跨线程更新 UI 的规则？ | 只有 GUI 线程能碰 widget；跨线程用信号（队列连接）传递；本项目的读取线程只 `emit`，绝不直接改控件 |
| QAbstractItemModel 怎么写？ | `index/parent/rowCount/columnCount/data/setData/flags` + `beginInsertRows/endInsertRows`；配 `QSortFilterProxyModel` 过滤，delegate 管绘制 |
| 大网格怎么不卡？ | LOD/降采样、actor 复用不重建 pipeline、picking 用包围盒加速、渲染与计算分线程、分块流式加载 |
| VTK 怎么嵌 Qt？ | `QVTKOpenGLNativeWidget` + `vtkGenericOpenGLRenderWindow`；渲染只能在主线程；交互器事件桥到 Qt 信号 |
| 高 DPI 怎么处理？ | Qt5 两个 attribute；Qt6 默认；避免像素常量，用布局/字体度量/`devicePixelRatio` |
| 你没做性能优化吧？ | **诚实**：*"日志追加实测 0.03ms/行，够用，所以我没优化——我更愿意先修状态反馈丢失这种真问题。"*（不乱优化 = 工程成熟） |

### 6.3 别踩的坑

- ❌ 别说"我做了个 CAE 软件"——会被追问网格质量、单元类型、收敛判据、并行分区。
- ❌ 别花 10 分钟讲 UI 配色——CAE 面试官更关心数据流、性能、扩展性。
- ❌ 别只放截图——要能现场跑、能当场改 bug（所以 §2.1 那三个 bug 留着当"现场演示"也行）。
- ❌ 别回避 C++——不会就说"我在补"，并给出具体进度（写了多少行、用了什么）。

---

## 7. 优先级总表

| 优先级 | 事项 | 收益 | 工时 |
|---|---|---|---|
| P0 ✅ | 修 3 个缺陷（完成文案/停止时间戳/副标题裁切） | 观感 + 可讲 | 2–3h |
| P0 ✅ | 总览加滚动容器 + 最小尺寸 + max-width | 高 DPI/小屏可用 | 2h |
| P1 ✅ | 顶栏标题层级、按钮分级、图标 | 专业度立刻提升 | 4–6h |
| P1 ✅ | 日志区 splitter / 自动贴合（批量 flush 实测不需要） | 布局稳定 | 3h |
| P1 ✅ | 配置页：必填标记/搜索/折叠/Ctrl+S/单一 reveal | 可用性 | 6–8h |
| P1 ✅ | 去内联样式、字号归 QSS、字体回退补 Linux | 设计系统健康 | 2h |
| P2 | **换 PySide6** | 许可证 + 现代 Qt | 4–6h |
| P2 | **Model/View（参数表 + 任务树）** | **面试核弹** | 2–3d |
| P2 | Dock 布局 + QAction 命令系统 + Undo | **面试核弹** | 2–3d |
| P3 | CAE 垂直切片（VTK + 求解 + 结果） | **决定能不能投 CAE** | 2 周 |
| P3 | C++/Qt6/CMake 骨架复刻 | 通过 C++ 岗初筛 | 2 周 |

---

## 8. 档 1 实施记录（已完成）

范围：只动界面层，不改 `upload.ps1`、`key.txt` 格式、后端进程/脱敏逻辑。测试从 **53 → 58 全绿**。

### 8.1 改动清单

| 文件 | 改动 |
|---|---|
| `dafeiyu_gui/ui/icons.py`（新增） | 单色 SVG 图标加载器：渲染后按主题 `SourceIn` 着色并缓存，深/浅色共用一套资源；QtSvg 缺失时自动退化为无图标 |
| `dafeiyu_gui/assets/icons/*.svg`（新增 12 个） | grid / sliders / help / deploy / refresh / play / stop / key / lock / terminal / folder / search |
| `ui/widgets.py` | `StatusCard` 去掉固定高度、副标题省略号+tooltip；`SectionCard` 支持折叠；新增 `ResultBar`；`LogView` 去掉硬编码字体；删除死代码 |
| `ui/overview.py` | 内容区滚动 + 顶部/日志统一 1120 内容列；`QSplitter` 上下分栏（自动贴合、拖动后不再干预）；结果条；按钮分级与图标；`mark_stopped()` 同步时间 |
| `ui/settings_page.py` | 必填星号（固定宽度槽位，标签右缘对齐）、逐字段"已修改"高亮、分组折叠、搜索 + 只看必填（重建 `QFormLayout` 行避免空行）、去掉全局显示密码、placeholder 语义修正 |
| `ui/main_window.py` | 顶栏改为当前页面名+说明；最小尺寸 900×620；`Ctrl+S`；主题切换时重着色图标；`finish_operation` 传结果级别；停止后走 `overview.mark_stopped()` |
| `ui/theme.py` | 新增 `on_primary` 语义色（修深色主按钮白字对比度不足）、`ResultBar`/`SubtleButton`/`SectionToggle`/`RequiredMark`/字段脏标记样式、`QSplitter` 去抓手、Linux 中文字体回退、小字 8.5pt→9pt |
| `ui/help_page.py` | 去掉与顶栏重复的标题；正文内容列同样收窄居中 |
| `build_gui_exe.ps1` | `--add-data` 从单个 `app.svg` 改为整个 `assets/` 目录（否则打包后没有图标） |
| `tests/test_ui_smoke.py` | 新增 5 个回归用例（见 8.3） |
| `README.md` / `docs/gui-preview.png` | 更新界面说明与预览图 |

### 8.2 报告条目 → 实施结果

| 报告条目 | 结果 | 验证 |
|---|---|---|
| P0-1 完成文案看不到 | 新增 `ResultBar`，`finish_operation()` 把结论写进结果条并保留 | 截图 `05_overview_result.png`；`RESULT_BAR_VISIBLE=True`；单测 |
| P0-2 停止后时间戳不动 | `OverviewPage.mark_stopped()` 同时更新卡片与「最近检查」并标注"本地停止操作" | 单测 `test_stop_action_refreshes_checked_hint` |
| P0-3 状态卡副标题被裁 | 去掉 `setFixedHeight(84/16)`；副标题按宽度 `elidedText` + 完整 tooltip | 卡片实测 83px、副标题 18px（字体行高 18）；单测验证省略号与 tooltip |
| P0-4 小屏/高 DPI 放不下 | 总览套 `QScrollArea`；最小尺寸 980×760 → **900×620** | 截图 `02_overview_min_size.png`（900×620 正常滚动） |
| 双主标题打架 | 顶栏显示「总览/配置/帮助 + 说明」，页面内标题删除 | 截图 01/06/08 |
| 大屏失控 | 顶栏、内容、日志统一 `MAX_CONTENT_WIDTH=1120` 居中 | 截图 `03_overview_wide.png`（1600 宽下三者对齐） |
| 日志占 40% 且空置 | 改为 `QSplitter`，日志最小 140px；上方面板按内容高度自动贴合 | `SPLITTER_SIZES=[457,242]`；横幅出现时不再切半（截图 11） |
| 运行时布局跳动 | 进度面板出现时自动重新贴合；结果条接替进度面板的位置 | 截图 04/05 |
| 按钮无层级 / 零图标 | 部署 primary、停止 danger 描边、维护操作 subtle；8 个操作 + 3 个导航配主题色图标 | 截图 01/09 |
| 内联样式破坏设计系统 | 删除全部 `setStyleSheet("font-size: …")`，字号统一回 QSS | `grep setStyleSheet` 仅剩 QSS 内文本 |
| 深色主按钮对比度差 | 新增 `on_primary`（浅色 #FFFFFF / 深色 #0B1220），按钮文字与图标同时切换 | 截图 09/10 |
| 配置页 16 字段平铺 | 搜索 + 只看必填 + 分组折叠 + 必填星号 + 字段级脏标记 | 截图 06/07；单测 `test_settings_filter_rebuilds_rows`、`test_required_fields_are_marked` |
| 两套显示密码机制 | 只保留每行「显示」按钮 | 截图 06 |
| placeholder 语义反转 | 必填显示「必填」，可选显示「可选，留空则不启用」 | 截图 06 |
| 缺 `Ctrl+S` | 新增快捷键；无修改时只在状态栏提示，不重复写盘 | `check.py` 实测 |

### 8.3 新增测试（58 通过）

1. `test_finish_operation_keeps_result_visible` — 进度面板收起后结论仍可见。
2. `test_stop_action_refreshes_checked_hint` — 停止后「最近检查」同步。
3. `test_status_detail_is_elided_with_full_tooltip` — 省略号 + tooltip 全文。
4. `test_settings_filter_rebuilds_rows` — 搜索后隐藏字段/分组，清空后恢复。
5. `test_required_fields_are_marked` — 6 个必填项都有星号。

### 8.4 已知取舍（留到档 2）

- 仍是手写按钮而不是 `QAction` 命令系统，也没有菜单栏/工具栏/右键菜单。
- 参数表还是 `QFormLayout` 手工行，没有 `QAbstractTableModel`（搜索/筛选靠重建行实现）。
- 没有 i18n、没有无障碍名称；QSS 仍用 `pt` 固定字号（系统大字体不生效的问题未根治）。
- 日志仍是逐行 `insertText`（实测 0.06ms/行，够用），没做批量 flush。
- 未换 PySide6，许可证问题仍在。

## 附录 A：本文证据怎么复现

- 截图与测量脚本：`_ui_analysis/shoot.py`（总览/配置/帮助/深色/运行中/最小尺寸/宽屏 + 日志性能）
- 高 DPI 与大字号：`_ui_analysis/dpi_test.py`（`QT_SCALE_FACTOR=1.5`、13pt 应用字体）
- 产物：`_ui_analysis/shots/*.png`
- 复现命令（Windows）：
  ```powershell
  $env:QT_QPA_FONTDIR="C:\Windows\Fonts"
  $env:PYTHONIOENCODING="utf-8"
  python _ui_analysis\shoot.py
  $env:QT_SCALE_FACTOR="1.5"; python _ui_analysis\dpi_test.py dpi150
  ```
  （脚本用 `_ui_analysis/proj/` 下的**合成 key.txt**，不读真实凭证）

## 附录 B：代码改动范围

- 评估阶段未改动项目代码；「档 1」只改界面层与测试（见 §8.1），不触碰 `upload.ps1`、`deploy.sh`、`key.txt` 格式与脱敏逻辑。
- `_ui_analysis/` 是截图/测量用的临时脚本与产物（脚本用 `_ui_analysis/proj/` 下的**合成 key.txt**，不读取真实凭证），可随时整体删除。
