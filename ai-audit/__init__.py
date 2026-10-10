"""ai_audit 包初始化（目录部署时命名为 ai_audit，使其可被框架导入）。"""

# =============================================================================
# ai_audit 包初始化
# =============================================================================
# 说明：使 ai-audit 目录（复制到框架仓库根目录时命名为 ai_audit）成为可导入
#       的 Python 包，以便框架通过 importlib.resources.files('ai_audit') 加载
#       taskflow / personality / model_config。
#
#       框架运行命令使用顶层模块路径 ai_audit.* 引用本包下的资源文件：
#         - ai_audit.alert_triage_example            （taskflow，.yaml）
#         - ai_audit.personalities.python_auditer    （personality，.yaml）
#         - ai_audit.model_config                    （model_config，.yaml）
#
#       本文件为空即可，无需导出任何符号。
# =============================================================================
