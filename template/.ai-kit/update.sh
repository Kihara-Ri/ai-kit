#!/usr/bin/env bash
# 升级套件：只覆盖 .ai-kit/kit-files.txt 里列出的文件，不动项目自己的文件
REPO="${AI_KIT_REPO:-Kihara-Ri/ai-kit}"
REF="${AI_KIT_REF:-main}"
curl -fsSL "https://raw.githubusercontent.com/$REPO/$REF/install.sh" | bash -s -- --update
