# Changelog

## 0.3.1
- `install.sh` 不再覆盖项目已有的 `core.hooksPath`（只在未设置或已是 `.githooks` 时才设置），避免顶掉项目自己的钩子目录

## 0.3.0
- 新增 `ship`（`.ai-kit/ship/`）：单机裸机发布工具，release 目录 + current 软链 + systemd；
  预检、构建产物一致性检查、发布前数据库快照与快照轮换、回滚时按 schema 恢复快照、发布锁、
  `deploy.log`、可选公网检查、`rollback` / `unlock` / `status`；配置见 `deploy.toml.example`，测试见 `tests/test_ship.py`

## 0.2.1
- `check-hygiene.sh` 支持 `HYGIENE_ALLOW`（config.sh）：随产品发布的大文件或压缩包可列为 R12 例外

## 0.2.0
- 新增 `.ai-kit/config.sh`（源码目录、组件目录、日志触发目录、注册表路径、行数上限）与 `hooks/_lib.sh`
- pre-commit 只检查暂存文件；新增 `.ai-kit/legacy.txt` 历史遗留白名单，便于接入已有项目
- 新增 `EXTRA_PRECOMMIT`，可串联项目自己的提交检查
- R4/R9 检查支持多个组件目录与多个 `package.json`

## 0.1.0
- 初版：12 条铁律（灰度、组件复用、图形优先、日志溯源、目录结构、注释、仓库卫生）
- 钩子：SessionStart 注入历史、PostToolUse 设计检查、Stop 要求日志
- git pre-commit 门禁：设计、结构、卫生、日志、注册表、依赖决策
- 灰度 tokens（深浅主题）、日志 / 决策 / 已知问题模板
- `install.sh` 一键安装与升级
