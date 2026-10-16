#!/usr/bin/env bash
# 目录结构与文件长度（R10 R11）：样式跟同名组件在一起；文件不超过上限；组件文件要有头部注释
# 用法：check-structure.sh [--staged]
. "$(dirname "$0")/_lib.sh"
[ "${1:-}" = "--staged" ] && ONLY_STAGED=1
fail=0

# 1. 样式文件必须有同名组件（tokens.css / reset.css 除外）
while IFS= read -r css; do
  case "$(basename "$css")" in tokens.css|reset.css) continue ;; esac
  base="${css%.*}"; base="${base%.module}"
  found=0
  for ext in tsx jsx vue svelte ts js; do [ -f "$base.$ext" ] && found=1; done
  [ "$found" = 0 ] && { echo "R10：样式文件没有同名组件：$css（样式应与组件同目录同名）" >&2; fail=1; }
done < <(candidates '\.(css|scss)$')

# 2. 文件长度上限
while IFS= read -r f; do
  n=$(wc -l < "$f")
  [ "$n" -gt "$MAX_LINES" ] && { echo "R10：$f 有 $n 行，超过 $MAX_LINES，请拆分" >&2; fail=1; }
done < <(candidates '\.(ts|tsx|js|jsx|vue|svelte|css|scss)$')

# 3. 组件文件前 5 行必须有注释（用途 / props）
while IFS= read -r f; do
  under "$f" "$COMPONENT_DIRS" || continue
  head -5 "$f" | grep -qE '^\s*(//|/\*|\*|<!--)' || { echo "R11：$f 缺少头部注释" >&2; fail=1; }
done < <(candidates '\.(tsx|jsx|vue|svelte)$')

exit $((fail * 2))
