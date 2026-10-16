#!/usr/bin/env bash
# 钩子共用库：读取配置、枚举待检查文件。被其他钩子 source，不单独运行。
ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$ROOT" || exit 0

SRC_DIRS="src"; COMPONENT_DIRS="src/components"; LOG_TRIGGER_DIRS="src app components"
REGISTRY="components/REGISTRY.md"; MAX_LINES=200
LEGACY_FILE=".ai-kit/legacy.txt"; PACKAGE_JSONS="package.json"
# shellcheck disable=SC1091
[ -f .ai-kit/config.sh ] && . .ai-kit/config.sh

# 路径是否在 dirs（空格分隔）之下
under() { local p="$1" d; shift; for d in $1; do case "$p" in "$d"/*) return 0 ;; esac; done; return 1; }
# 是否列入历史遗留白名单
is_legacy() { [ -f "$LEGACY_FILE" ] && grep -qxF "$1" "$LEGACY_FILE"; }

# 候选文件：ONLY_STAGED=1 时只看暂存区的新增/修改，否则扫描整个源码目录；
# 已排除历史遗留文件。$1 = 路径的扩展正则。
candidates() {
  if [ "${ONLY_STAGED:-0}" = 1 ]; then
    git diff --cached --name-only --diff-filter=AM
  else
    local d; for d in $SRC_DIRS; do [ -d "$d" ] && find "$d" -type f; done
  fi | grep -E "$1" | while IFS= read -r f; do
    under "$f" "$SRC_DIRS" && ! is_legacy "$f" && echo "$f"
  done
}
