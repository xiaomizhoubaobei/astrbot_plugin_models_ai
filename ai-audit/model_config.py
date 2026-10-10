"""OpenAI 兼容上游模型配置（model_config）参考文档（框架不读取本 .py）。"""

# =============================================================================
# OpenAI 兼容上游模型配置（model_config）— 参考文档
# =============================================================================
# ⚠️ 注意：框架的 -m 参数只读取 .yaml 文件（model_config.yaml），本 .py 文件
#         仅为配置说明与历史参考，框架运行时不读取它。实际配置请修改
#         同目录下的 model_config.yaml。
#
# 用途：为 AI 审计 taskflow（alert_triage_example.yaml）声明使用的 API 类型，
#       并说明“模型名改由环境变量 COPILOT_DEFAULT_MODEL 提供”，从而免改代码
#       即可在 .github/workflows/ai-audit-scheduled.yml 通过仓库 Secret
#       AI_MODEL_NAME 灵活切换模型。
#
# 模型来源：
#   框架在 agent.py 里选择模型时读取环境变量：
#       COPILOT_DEFAULT_MODEL —— 覆盖默认模型，即实际调用的模型名
#   本仓库工作流把 Secret `AI_MODEL_NAME` 透传给 COPILOT_DEFAULT_MODEL，
#   因此修改模型只需在仓库 Secret 里改 AI_MODEL_NAME，而无需改本仓库代码。
#
# 背景：本框架底层基于 OpenAI Agents Python SDK，直接构造 AsyncOpenAI 客户端：
#       client = AsyncOpenAI(base_url=<endpoint>, api_key=<token>)
#       其中 endpoint 与 token 的来源有二：
#         1) 环境变量：AI_API_ENDPOINT / AI_API_TOKEN（或 COPILOT_TOKEN）
#         2) 本 model_config 文件里按模型显式指定 endpoint / token（token 指向某环境变量名）
#       对未知端点会兜底为通用 custom provider，因此任何实现了 OpenAI
#       /v1/chat/completions 协议的上游都能直接接入：
#         - 本地 vLLM / Ollama 的 OpenAI 兼容口
#         - DeepSeek / 通义千问(Qwen) / Moonshot 等国产厂商的 OpenAI 兼容接口
#
# 使用方式（在运行命令中通过 -m 指定本模块路径）：
#   COPILOT_DEFAULT_MODEL=<你的模型名> \
#   AI_API_ENDPOINT=https://api.deepseek.com/v1 \
#   AI_API_TOKEN=<你的APIKey> \
#   hatch run main -t ai_audit.alert_triage_example \
#       -m ai_audit.model_config
#
# 前提：所选上游必须支持函数调用（tool calling），因为 AI 审计 taskflow
#       依赖工具调用；框架对自定义 provider 默认按“支持”乐观处理，
#       建议先在单个告警上跑通验证。
#
# 适配语言：Python
# 框架：GitHubSecurityLab/seclab-taskflow-agent
# =============================================================================

# 模型名：由环境变量 COPILOT_DEFAULT_MODEL 提供，仓库工作流把 Secret
#         AI_MODEL_NAME 透传给它。示例取值（不再硬编码进仓库）：
#  - DeepSeek：      deepseek-v4-flash / deepseek-chat
#  - 通义千问 Qwen： qwen-plus / qwen-max
#  - Moonshot：      moonshot-v1-8k / kimi-k2 等
#  - 本地 vLLM：     你部署的 model 名称
# 本文件中的 MODEL_NAME 仅为“预期用法示意”，框架并不会真正读取它，
# 实际生效的模型名请通过工作流的 AI_MODEL_NAME Secret 设置。
MODEL_NAME = ""  # 占位：改为由环境变量 COPILOT_DEFAULT_MODEL 提供

# API 类型：chat_completions 走 OpenAIChatCompletionsModel（OpenAI 兼容标准协议）
API_TYPE = "chat_completions"

# 模型名环境变量名：运行时框架读取它以确定实际调用的模型
MODEL_ENV = "COPILOT_DEFAULT_MODEL"

# 端点环境变量名：运行时从该环境变量读取上游 base_url（如 https://api.deepseek.com/v1）
ENDPOINT_ENV = "AI_API_ENDPOINT"

# Token 环境变量名：运行时从该环境变量读取对应厂商的 API Key
TOKEN_ENV = "AI_API_TOKEN"


def get_model_config():
    """Return the framework-recognisable model config structure (illustrative only).

    端点（endpoint）、密钥（token）与模型名均以“环境变量名”形式声明，
    运行时由框架从进程环境读取并解析，避免把密钥/模型硬编码进仓库。
    """
    return {
        "model_env": MODEL_ENV,  # 模型名取自该环境变量
        "model": MODEL_NAME,  # 仅示意，实际请设 COPILOT_DEFAULT_MODEL 环境变量
        "api_type": API_TYPE,
        "endpoint_env": ENDPOINT_ENV,
        "token_env": TOKEN_ENV,
    }
