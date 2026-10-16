#!/usr/bin/env bash
# PostToolUse 钩子：AI 每改完一个文件，立刻检查设计纪律（R1 R2）
f=$(jq -r '.tool_input.file_path // empty')
[ -z "$f" ] && exit 0
.ai-kit/hooks/check-design.sh "$f"
