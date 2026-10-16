#!/usr/bin/env bash
# 设计检查（R1 R2 R5）：颜色只能来自 token。钩子与 git 共用。
# 用法：check-design.sh [--staged] [文件...]   不带文件则检查源码目录
# 某行确需例外（如 CSS 选择器 #add），在该行加注释 ai-kit-ignore，并在日志里写明原因。
. "$(dirname "$0")/_lib.sh"
[ "${1:-}" = "--staged" ] && { ONLY_STAGED=1; shift; }

color='#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(|oklch\(|\b(bg|text|border|fill|stroke|ring)-(red|blue|green|yellow|orange|purple|pink|indigo|teal|cyan|amber|lime|emerald|sky|violet|fuchsia|rose)-[0-9]'
ext='\.(ts|tsx|js|jsx|css|scss|vue|svelte)$'

if [ $# -gt 0 ]; then
  files=$(for f in "$@"; do f="${f#$ROOT/}"; echo "$f" | grep -E "$ext" | grep -vE '(^|/)tokens\.css$' ; done | while IFS= read -r f; do under "$f" "$SRC_DIRS" && ! is_legacy "$f" && echo "$f"; done)
else
  files=$(candidates "$ext" | grep -vE '(^|/)tokens\.css$')
fi
[ -z "$files" ] && exit 0

bad=$(echo "$files" | while IFS= read -r f; do grep -nHE "$color" "$f" 2>/dev/null; done | grep -v 'ai-kit-ignore' || true)
if [ -n "$bad" ]; then
  echo "违反 R1/R2：发现字面量颜色或彩色类名，请改用 var(--token)：" >&2
  echo "$bad" | head -20 >&2
  exit 2
fi
