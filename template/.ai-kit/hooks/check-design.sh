#!/usr/bin/env bash
# 设计检查（R1 R2 R5）：钩子与 git 共用。
# 用法：check-design.sh [文件或目录...]   默认检查 src
# 某一行确实需要例外（如 CSS 选择器 #add），在该行加注释 ai-kit-ignore，并在日志里写明原因。
targets=("${@:-src}")
inc=(--include=*.ts --include=*.tsx --include=*.js --include=*.jsx
     --include=*.css --include=*.scss --include=*.vue --include=*.svelte)
color='#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(|oklch\(|\b(bg|text|border|fill|stroke|ring)-(red|blue|green|yellow|orange|purple|pink|indigo|teal|cyan|amber|lime|emerald|sky|violet|fuchsia|rose)-[0-9]'

bad=$(grep -rnE "$color" "${inc[@]}" --exclude=tokens.css "${targets[@]}" 2>/dev/null | grep -v 'ai-kit-ignore' || true)
if [ -n "$bad" ]; then
  echo "违反 R1/R2：发现字面量颜色或彩色类名，请改用 var(--token)：" >&2
  echo "$bad" | head -20 >&2
  exit 2
fi
