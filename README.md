# ai-kit

让任何 AI 都严格遵循我的前端纪律：灰度设计、组件复用、可溯源的日志、干净的仓库。
一条命令装进任何项目，之后由**说明 → 钩子 → git 门禁**三层约束 AI。

## 安装

在项目根目录运行（需要 `git`、`curl`、`jq`）：

```bash
curl -fsSL https://raw.githubusercontent.com/Kihara-Ri/ai-kit/main/install.sh | bash
```

或者用 degit 只拷文件（不会启用 git 钩子，需手动 `git config core.hooksPath .githooks`）：

```bash
npx degit Kihara-Ri/ai-kit/template .
```

安装是**只新增、不覆盖**：已存在的文件会跳过，`.gitignore` 只追加缺失的行。

## 升级

```bash
bash .ai-kit/update.sh
```

只覆盖 `.ai-kit/kit-files.txt` 里列出的套件文件（规则、钩子脚本、pre-commit）。你自己的 `AGENTS.md`、`docs/`、`components/REGISTRY.md`、`tokens/tokens.css`、`.claude/settings.json` 不会被动。

固定版本：`AI_KIT_REF=v0.1.0 bash .ai-kit/update.sh`。

## 装进去了什么

```text
AGENTS.md                 给所有 AI 的入口（短）；项目专属说明写在末尾
CLAUDE.md                 仅一行 @AGENTS.md
.ai-kit/rules.md          12 条铁律，每条带验证方式
.ai-kit/hooks/            session-context · post-edit · check-design · check-structure · check-hygiene · require-log
.claude/settings.json     Claude Code 钩子配置
.githooks/pre-commit      与 AI 无关的硬门禁
.gitignore                R12：不提交无关配置和数据
tokens/tokens.css         灰度 token（深浅主题、间距、圆角、字号）
components/REGISTRY.md    组件注册表
.ai-kit/ship/             发布工具 ship（ship.py · README · deploy.toml.example）
docs/log/ DECISIONS.md KNOWN-ISSUES.md   日志、决策、已知问题
```

## 接入已有项目

套件为"从零开始"设计，接入已有项目时：

1. 编辑 `.ai-kit/config.sh`：设置源码目录（`SRC_DIRS`）、组件目录、日志触发目录、注册表路径等。
2. 把**历史遗留文件**逐行列入 `.ai-kit/legacy.txt`（超长文件、旧样式、含字面量颜色的文件），它们不受 R1/R2/R10/R11 检查；新文件和新改动照常受检。
3. 提交时 pre-commit **只检查暂存的文件**，不会因为存量代码阻塞所有提交。
4. 项目已有自己的提交检查（如数据泄漏扫描）：在 `config.sh` 设置 `EXTRA_PRECOMMIT="..."` 即可接入同一道门禁。

## 三层约束

| 层 | 机制 | 对谁有效 |
| --- | --- | --- |
| 说明 | `AGENTS.md` + `rules.md` | 所有 AI（无强制力） |
| 钩子 | `.claude/settings.json` | Claude Code（拦截并反馈） |
| 门禁 | `.githooks/pre-commit` | 任何 AI 与人（提交时必须通过） |

## 发布工具 ship

套件还带一个与前端纪律无关的小工具：`.ai-kit/ship/ship.py`，给「一台服务器上的小项目」用的发布 / 回滚工具
（release 目录 + 软链 + systemd，可选数据库快照，回滚时按 schema 恢复）。只用 Python 标准库，复制
`.ai-kit/ship/deploy.toml.example` 为 `deploy.toml` 即可使用。详见 `.ai-kit/ship/README.md`。

## 临时绕过

钩子误伤时：`git commit --no-verify`，并在当次日志里写明原因。某一行确需例外（如 CSS 选择器 `#add`），该行加注释 `ai-kit-ignore`。

## 已知限制

- 源码与组件目录由 `.ai-kit/config.sh` 配置，默认 `src/`。
- 颜色检查是正则扫描，可能误报 `#add` 之类的选择器；用 `ai-kit-ignore` 标注。
- Claude Code 钩子的事件名和字段随版本演进，升级后请核对官方文档。
- Cursor、Codex 等没有同款钩子，靠 `AGENTS.md` 与 git 门禁约束。

完整的设计依据与规则说明见项目的设计系统文档。
