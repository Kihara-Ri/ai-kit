# 规则：12 条铁律

> 放在项目的 `.ai-kit/rules.md`，由 `AGENTS.md` 引用。每条都有"验证"——能自动检查的交给钩子，不能的交给你抽查。

## 视觉

**R1 只用灰度。**
设计稿、原型、代码里不得出现任何有色相的颜色。
验证：`check-design.sh` 扫描 hex / rgb / hsl / 彩色类名，除 `tokens.css` 外一律失败。

**R2 颜色只能来自 token。**
不写字面量颜色，写 `var(--ink)`。需要新层次，先在 `tokens.json` 里加，并写 `usage`。
验证：同上。

**R3 状态不靠颜色。**
用形状（实心/空心、对勾/叉）、字重、线宽、位置表达状态。
验证：人工抽查；组件注册表中每个状态型组件要列出它的"非颜色区分方式"。

## 前端结构

**R4 先查注册表，再写组件。**
新建任何 UI 前，必须先读 `components/REGISTRY.md`。已有相似组件时，**扩展它的 props**，不得新建近似品。同一段 UI 出现第二次，必须抽成组件。
验证：新增组件文件时，`REGISTRY.md` 必须同时被修改（pre-commit 检查）。

**R5 数值只来自 token。**
间距、圆角、字号、阴影只用 token；不写 `13px`、`margin: 7px`。
验证：脚本扫描 `px` 字面量（白名单：`0`、`1px` 边线）。

**R6 图形优先，文字极少。**
界面文案只留标题与 ≤4 词的标签。不写说明段落、欢迎语、占位废话；能用图标/图表/形状的不用字。
验证：人工抽查 + 评审清单。

## 纪律

**R7 改完必留痕。**
任何代码改动结束前，必须新增 `docs/log/日期-slug.md`：改了什么 / 出了什么问题 / 怎么解决 / 可能带来什么新问题。
验证：`Stop` 钩子 + pre-commit。

**R8 先查历史，再下结论。**
动手前读最近 3 条日志、`DECISIONS.md`、`KNOWN-ISSUES.md`。看到"奇怪的写法"，先搜决策编号（如 `D-004`），确认是妥协还是错误，**不得顺手重构**。
验证：`SessionStart` 钩子把这些内容直接注入上下文。

**R9 只改被要求的。**
不做顺带的重命名、格式化、依赖升级。发现问题写进 `KNOWN-ISSUES.md`，不要擅自修。引入新依赖或新模式，必须先写一条决策记录。
验证：评审 diff；新依赖由 pre-commit 检查是否伴随 `DECISIONS.md` 变更。

## 代码组织

**R10 一个组件一个目录，样式跟着组件走。**
每个组件自成一个文件夹，组件代码与样式放在一起、同名：`Button/Button.tsx` + `Button/Button.css`（或 CSS Modules / 单文件组件的 `<style>`）。**不得**建立堆放多个组件样式的 `styles/` 目录或巨型 `global.css`；全局样式只允许 `tokens.css` 与 `reset.css`。按功能分层（`components/` `features/` `lib/`），依赖只能向下：页面可引用组件，组件不得引用页面。
验证：脚本检查除 `tokens.css`、`reset.css` 外的样式文件必须与同名组件文件同目录；单个文件超过 200 行即失败（强制拆分）。

**R11 注释写"为什么"，不写"是什么"。**
每个组件文件顶部一段注释：用途、关键 props、不该怎么用。非显而易见的逻辑、绕路写法、妥协处写原因，并引用决策编号（`// 见 D-004`）。不留被注释掉的旧代码，不写复述代码的注释。
验证：lint 规则禁止注释掉的代码块；组件文件缺少头部注释时 pre-commit 报警。

## 仓库卫生

**R12 不提交不必要的配置和数据。**
只提交源码、文档和**必需**的配置。下列内容一律不进库：
- 构建与依赖产物：`node_modules`、`dist`、`build`、`coverage`、各类 `.cache`
- 密钥与本地环境：`.env*`（`.env.example` 除外）、`*.local.json`、个人编辑器设置（`.idea`、`.vscode`）
- 数据与杂物：数据库、导出文件、压缩包、日志、截图、临时测试数据、单个超过 500 KB 的文件
- AI 的本地状态：`.claude/settings.local.json`、各工具的缓存与会话文件

新增配置文件（`*.config.*`、`.*rc`）必须先在 `DECISIONS.md` 写明为什么需要；能用默认值就不加配置。测试数据放 `fixtures/` 且保持最小。`package-lock.json` 等锁文件**要**提交。
验证：`.gitignore` 模板 + pre-commit 的 `check-hygiene.sh`。

---

## 值得再加的规范（按收益排序）

| 优先 | 规范 | 为什么对 AI 协作特别有用 | 怎么强制 |
| --- | --- | --- | --- |
| 高 | **用现成工具，不手写检查** | ESLint / Prettier / Stylelint 比自写脚本可靠，AI 的错误输出也更清晰 | pre-commit 跑 lint；Stylelint 可限制颜色只能用 `var(--…)` |
| 高 | **TypeScript strict，禁 `any`** | 类型是 AI 最容易读懂、也最难绕过的约束 | `tsconfig` strict + ESLint |
| 高 | **修 bug 必带回归测试** | 防止 AI 修好 A 又弄坏 B | pre-commit / CI 跑测试，日志里写明新增了哪个测试 |
| 高 | **依赖方向由工具检查** | 防止组件偷偷引用页面、循环依赖 | `eslint-plugin-boundaries` 或 `dependency-cruiser` |
| 中 | **文件、函数长度上限** | 逼 AI 拆分，而不是把所有东西塞一个文件 | ESLint `max-lines`、`max-lines-per-function` |
| 中 | **显式错误处理** | AI 常写空 `catch` 吞掉错误，问题被藏起来 | ESLint `no-empty`；日志里记录处理策略 |
| 中 | **无残留调试代码** | `console.log`、`TODO` 无编号会越积越多 | ESLint `no-console`；TODO 必须带 `I-` 编号 |
| 中 | **无障碍底线** | 灰度界面更依赖对比度与形状，键盘可达、aria 标签、4.5:1 对比度不可省 | `eslint-plugin-jsx-a11y` |
| 中 | **提交规范** | 小步提交、`feat/fix/refactor` 前缀，便于回溯与回滚 | `commitlint` 钩子 |
| 低 | **密钥不入库** | AI 可能把示例密钥写进代码 | `gitleaks` 加到 pre-commit |
| 低 | **新依赖需决策记录** | 防止 AI 为一个小功能引入一堆包 | 已在 R9 |

先别全上。建议顺序：R10 R11 → ESLint/Prettier/Stylelint → TypeScript strict → 依赖方向 → 回归测试。

---

## 写规则的三个技巧

1. **短**：`AGENTS.md` 控制在一屏内，细节放这里，AI 需要时再读。
2. **可验证**：每条规则写"验证"一栏。写不出来就改规则。
3. **说原因**：一句话理由比十句命令有效，AI 遇到边界情况能自行推理。

## 组件注册表格式（`components/REGISTRY.md`）

| 组件 | 用途 | 关键 props | 非颜色状态区分 | 日期 |
| --- | --- | --- | --- | --- |
| `Icon` | 所有图标 | `name` `size` | — | 2026-10-17 |
| `Meter` | 用条形图代替数字描述 | `value` `max` | 填充长度 | 2026-10-17 |

新组件必须先在此登记，再写代码。
