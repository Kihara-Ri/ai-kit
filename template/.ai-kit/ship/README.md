# ship — 单机裸机发布工具

一台服务器上的小项目：`release 目录 + current 软链 + systemd`，可选带需要快照的数据库。
只用 Python 标准库（3.11+，需要 `tomllib`）。不做容器和多机——那种场景用 Kamal 之类。

```sh
python3 .ai-kit/ship/ship.py deploy [--init] [--skip-tests] [--allow-dirty]
python3 .ai-kit/ship/ship.py rollback      # 回滚上一版（只切代码）
python3 .ai-kit/ship/ship.py unlock        # 释放残留发布锁
python3 .ai-kit/ship/ship.py status        # 版本 / release / 快照 / 锁 / 最近记录
```

## 流程

预检（未提交改动中止、未推送警告、测试关卡）→ 构建 → 构建产物须与已提交一致 → 打包 →
上传解压 → 停服务并快照 → 切软链重启 → 健康检查 → 失败自动回滚（**库结构被新版本改动过则先恢复快照**）→
清理旧 release 与旧快照 → 可选公网检查。每次发布写服务器上的 `deploy.log`。

## 配置

1. 复制 `.ai-kit/ship/deploy.toml.example` 为项目根的 `deploy.toml`，按项目改。
2. 个人信息（主机别名、域名）写 `deploy.local.toml` 并加入 `.gitignore`。
3. 环境变量优先：`SHIP_HOST` `SHIP_DIR` `SHIP_SERVICE` `SHIP_HEALTH_URL` `SHIP_PUBLIC_URL`
   `SHIP_KEEP_RELEASES` `SHIP_KEEP_SNAPSHOTS` `SHIP_LOCK_TTL` `SHIP_SETTLE`，`SHIP_CONFIG` / `SHIP_LOCAL_CONFIG` 指定文件。
4. `host = "local"` 表示在服务器本机运行（补丁更新器等），此时不读个人覆盖、不做预检。

要求：免密 ssh、免密 sudo；服务由 systemd 管理；健康检查地址在服务器上能 `curl` 并返回 JSON。

## 约定与边界

- 发布包是 `tar.gz`，根目录含版本文件（默认 `VERSION`），其内容必须等于健康检查返回的版本字段。
- 数据库快照在**服务停止后**复制，保证一致；`kind = "command"` 可接任意数据库，只需提供快照 / 恢复 / 读取 schema 的命令。
- 自动恢复快照只在 schema 版本变化时触发；同 schema 的数据迁移问题仍需人工判断。
- 发布锁只提示持有者与时长，不自动解锁；确认没有发布在运行后用 `unlock`。
- 退出码：0 成功；1 失败；3 已发布但公网检查失败（不回滚，多半是反代 / 证书 / DNS）。
