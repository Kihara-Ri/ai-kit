#!/usr/bin/env bash
# ai-kit 安装 / 升级脚本
#   安装：在项目根目录运行   curl -fsSL https://raw.githubusercontent.com/Kihara-Ri/ai-kit/main/install.sh | bash
#   升级：                   curl -fsSL https://raw.githubusercontent.com/Kihara-Ri/ai-kit/main/install.sh | bash -s -- --update
# 环境变量：AI_KIT_REPO（默认 Kihara-Ri/ai-kit）、AI_KIT_REF（分支或标签，默认 main）、
#           AI_KIT_SRC（本地套件目录，用于测试，跳过 git clone）
#
# 规则：
#   安装模式：只新增文件，绝不覆盖项目里已有的文件；.gitignore 只追加缺失的行。
#   升级模式：只覆盖 .ai-kit/kit-files.txt 里列出的"套件文件"，项目自己的文件（docs、注册表、AGENTS.md 等）不动。
set -euo pipefail

REPO="${AI_KIT_REPO:-Kihara-Ri/ai-kit}"
REF="${AI_KIT_REF:-main}"
MODE="install"
[ "${1:-}" = "--update" ] && MODE="update"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

if [ -n "${AI_KIT_SRC:-}" ]; then
  src="$AI_KIT_SRC/template"
else
  git clone --depth 1 --branch "$REF" "https://github.com/$REPO.git" "$tmp/kit" >/dev/null 2>&1 \
    || { echo "无法获取 $REPO@$REF，请检查仓库名、网络，或仓库是否公开。" >&2; exit 1; }
  src="$tmp/kit/template"
fi
[ -d "$src" ] || { echo "找不到套件目录：$src" >&2; exit 1; }

# 套件文件清单（升级时只覆盖这些）
kit_list="$src/.ai-kit/kit-files.txt"
is_kit_file() { grep -qxF "$1" "$kit_list"; }

added=0; skipped=0; updated=0

while IFS= read -r f; do
  rel="${f#$src/}"
  dest="./$rel"

  # .gitignore 特殊处理：只追加缺失的行
  if [ "$rel" = ".gitignore" ]; then
    [ "$MODE" = "update" ] && continue
    touch "$dest"
    while IFS= read -r line; do
      [ -z "$line" ] && continue
      grep -qxF "$line" "$dest" || echo "$line" >> "$dest"
    done < "$f"
    echo "合并  .gitignore"
    continue
  fi

  if [ "$MODE" = "update" ]; then
    if is_kit_file "$rel"; then
      mkdir -p "$(dirname "$dest")"; cp -p "$f" "$dest"
      echo "更新  $rel"; updated=$((updated + 1))
    fi
  else
    if [ -e "$dest" ]; then
      echo "跳过  $rel（已存在）"; skipped=$((skipped + 1))
    else
      mkdir -p "$(dirname "$dest")"; cp -p "$f" "$dest"
      echo "新增  $rel"; added=$((added + 1))
    fi
  fi
done < <(find "$src" -type f | sort)

chmod +x .ai-kit/hooks/*.sh .ai-kit/update.sh .ai-kit/ship/ship.py .githooks/pre-commit 2>/dev/null || true

# 启用 git 门禁
if git rev-parse --git-dir >/dev/null 2>&1; then
  # 项目已有自己的钩子目录（如 tools/hooks，里面再串联 .githooks）时不覆盖，只提示
  current_hooks="$(git config --get core.hooksPath || true)"
  if [ -z "$current_hooks" ] || [ "$current_hooks" = ".githooks" ]; then
    git config core.hooksPath .githooks
    echo "已启用 git 钩子：core.hooksPath = .githooks"
  else
    echo "保留已有的 core.hooksPath = $current_hooks（未改成 .githooks）；请确认它会调用 .githooks/pre-commit，见 config.sh 的 EXTRA_PRECOMMIT。"
  fi
else
  echo "提示：当前目录还不是 git 仓库。git init 之后运行：git config core.hooksPath .githooks"
fi

command -v jq >/dev/null 2>&1 || echo "提示：钩子依赖 jq，请先安装（macOS：brew install jq）。"

echo
echo "完成（$MODE）：新增 $added · 跳过 $skipped · 更新 $updated · 套件版本 $(cat .ai-kit/VERSION 2>/dev/null || echo '?')"
[ "$MODE" = "install" ] && echo "下一步：编辑 AGENTS.md 补充项目专属说明，然后让 AI 开工。"
exit 0
