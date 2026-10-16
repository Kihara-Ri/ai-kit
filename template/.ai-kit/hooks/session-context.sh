#!/usr/bin/env bash
# SessionStart 钩子（R8）：标准输出会作为上下文交给 AI，让它开工前先读历史
echo "== 最近 3 条日志 =="
ls -1t docs/log/*.md 2>/dev/null | grep -v _TEMPLATE | head -3 | while read -r f; do
  echo "--- $f"; head -30 "$f"
done
echo "== 架构决策 =="; cat docs/DECISIONS.md 2>/dev/null
echo "== 已知问题 =="; cat docs/KNOWN-ISSUES.md 2>/dev/null
echo "== 铁律 =="; cat .ai-kit/rules.md
