#!/usr/bin/env bash
# Stop 钩子（R7）：代码有改动却没有新日志，不准收工
. "$(dirname "$0")/_lib.sh"
input=$(cat)
# 已经被拦过一次就放行，避免死循环；git pre-commit 还会兜底
[ "$(echo "$input" | jq -r '.stop_hook_active // false')" = "true" ] && exit 0

changed=$(git status --porcelain | awk '{print $NF}')
code=""
for d in $LOG_TRIGGER_DIRS; do
  code="$code$(echo "$changed" | grep -E "^$d/" || true)"
done
log=$(echo "$changed" | grep -E '^docs/log/' || true)

if [ -n "$code" ] && [ -z "$log" ]; then
  echo "代码已改动，但 docs/log/ 没有新日志。请按 docs/log/_TEMPLATE.md 写一条：改了什么 / 出了什么问题 / 怎么解决 / 可能带来什么新问题。写完再结束。" >&2
  exit 2
fi
