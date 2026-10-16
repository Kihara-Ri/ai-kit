#!/usr/bin/env bash
# 仓库卫生（R12）：只检查本次暂存的新增/修改文件
staged=$(git diff --cached --name-only --diff-filter=AM)
[ -z "$staged" ] && exit 0
fail=0

# 1. 禁止的路径与文件类型（.env.example 允许）
bad=$(echo "$staged" | grep -vE '\.env\.example$' | grep -E \
  '(^|/)(node_modules|dist|build|coverage|\.next|\.turbo|\.cache|__pycache__|\.idea|\.vscode)/|(^|/)\.env($|\.)|\.(log|sqlite|db|zip|tar|gz)$|(^|/)\.DS_Store$|\.local\.json$' || true)
[ -n "$bad" ] && { echo "R12：这些文件不应进库，请移除并写入 .gitignore：" >&2; echo "$bad" >&2; fail=1; }

# 2. 单文件超过 500 KB
while IFS= read -r f; do
  [ -f "$f" ] && [ "$(wc -c < "$f")" -gt 512000 ] && { echo "R12：$f 超过 500 KB，不要提交大文件或数据" >&2; fail=1; }
done <<< "$staged"

# 3. 新增根目录配置文件，必须同时修改 DECISIONS.md
newcfg=$(git diff --cached --name-only --diff-filter=A | grep -E '^([^/]*\.config\.[^/]+|\.[^/]*rc[^/]*)$' || true)
if [ -n "$newcfg" ] && ! echo "$staged" | grep -q 'docs/DECISIONS.md'; then
  echo "R12：新增了配置文件，需要在 docs/DECISIONS.md 写明原因：" >&2; echo "$newcfg" >&2; fail=1
fi

exit $fail
