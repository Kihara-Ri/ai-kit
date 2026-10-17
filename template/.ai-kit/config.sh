# ai-kit 项目配置（项目自己维护，升级不会覆盖）
# 钩子脚本通过 hooks/_lib.sh 读取本文件。
SRC_DIRS="src"                        # 源码目录（空格分隔）
COMPONENT_DIRS="src/components"       # 需要头部注释（R11）的组件目录
LOG_TRIGGER_DIRS="src app components" # 这些目录有改动时必须带日志（R7）
REGISTRY="components/REGISTRY.md"     # 组件注册表路径（R4）
MAX_LINES=200                         # 单文件行数上限（R10）
LEGACY_FILE=".ai-kit/legacy.txt"      # 历史遗留文件白名单：每行一个路径，列入后不受 R1/R2/R10/R11 检查
PACKAGE_JSONS="package.json"          # 依赖变更需写决策（R9）
HYGIENE_ALLOW=""                    # 不受 R12（大文件/压缩包）检查的路径（扩展正则），如 '^plugins/.*\.zip$'
