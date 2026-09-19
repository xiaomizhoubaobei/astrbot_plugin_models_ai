# AGENT.md

本文件为 AI 编码助手（Agent）提供本仓库的项目上下文、开发约定与工作流程。
> 项目：`astrbot_plugin_models_ai` — AstrBot 的 AI 图像生成插件，接入 Gitee AI，支持文生图、风格转换、AI 图片编辑与多 Key 轮询。

---

## 1. 项目概览

| 项目 | 说明 |
| --- | --- |
| 名称 | `astrbot_plugin_models_ai` |
| 类型 | AstrBot 插件（Python） |
| 版本 | v0.0.6 |
| 作者 | 祁筱欣 |
| Python | 3.12+（CI 使用 black/flake8，声明 3.12+；pre-commit 中 black 指定 3.11） |
| 上游 API | Gitee AI（`https://ai.gitee.com/v1`，OpenAI 兼容接口） |
| 主要依赖 | `aiofiles`, `aiohttp`, `openai`, `deprecated`（另用 `httpx`） |

插件把 Gitee AI 的多模态生图能力封装为 AstrBot 指令 + LLM 工具，支持提示词比例解析、多 API Key 轮询、请求防抖、图片自动清理。

---

## 2. 目录结构

```
.
├── main.py                 # 插件主入口：AIImage(Star) 类、指令注册、LLM 工具注册、资源清理
├── metadata.yaml           # 插件元数据（name/desc/version/author/repo）
├── _conf_schema.json       # AstrBot 配置 schema（api_key/model/size 等）
├── requirements.txt        # 运行依赖
├── commands/               # 指令处理逻辑
│   ├── __init__.py         # 命令函数导出
│   ├── generate.py         # /ai-gitee generate 文生图
│   ├── style.py            # /ai-gitee style 风格转换（文生图/图生图）
│   ├── style_prompts.json  # 风格提示词字典（约 190+ 条，运行时加载）
│   ├── ai_edit.py          # /ai-gitee ai-edit AI 图片编辑
│   ├── text2image.py       # /ai-gitee text2image 模型列表
│   ├── switch_model.py     # /ai-gitee switch-model 切换模型
│   └── help.py             # /ai-gitee help 帮助
├── core/                   # 核心公共能力
│   ├── config.py           # 常量与配置解析（默认模型/尺寸/比例表等）
│   ├── client_manager.py   # AsyncOpenAI 客户端与 aiohttp/httpx 会话复用
│   ├── image_manager.py    # 图片下载/保存/base64 落盘/过期清理
│   ├── rate_limiter.py     # 防抖与并发控制
│   └── command_utils.py    # check_rate_limit / parse_prompt_and_size / 图片提取
├── gitee/                  # Gitee AI 接入层
│   ├── api_client.py       # GiteeAIClient：generate_image / get_models / edit_image
│   └── model_manager.py    # ModelLister：模型列表拉取与格式化
├── llm_tools/
│   └── draw.py             # LLM 工具 draw_image 实现
├── docs/                   # 文档（开发指南、功能总览、roadmap 等）
├── .github/workflows/      # CI：CodeQL、安全检查、PR 审查、release 等
├── .cnb.yml                # CNB 云端流水线（开发环境 + 同步至 GitHub）
└── install_agents.sh / install_gpg_keys.sh  # 环境/代理安装脚本
```

---

## 3. 核心架构与数据流

```
AstrBot 消息事件
      │
      ▼
main.py  AIImage(Star)   ── 指令组 ai-gitee / LLM 工具 draw_image
      │
      ├── commands/*       命令层：参数解析、防抖、调用 API、回包
      │        │
      │        └── core/command_utils.py  check_rate_limit / parse_prompt_and_size
      ▼
gitee/api_client.py  GiteeAIClient   ── 多 Key 轮询
      │
      ├── core/client_manager.py   AsyncOpenAI / aiohttp / httpx 复用
      └── core/image_manager.py    下载·base64 落盘·定期清理
                                     │
                                     ▼
                            本地图片目录（StarTools 数据目录/images）
```

- 命令层与工具层均通过 `plugin.api_client` / `plugin.rate_limiter` / `plugin.model_lister` 访问能力。
- 每个请求以 `user_id` 作为 `request_id`，统一走防抖 + `is_processing` 互斥。
- 生图响应支持 URL 或 base64 两种格式，统一由 `ImageManager` 落地为本地文件后回包。

---

## 4. 指令与 LLM 工具

指令组：`/ai-gitee`

| 指令 | 用法 | 说明 |
| --- | --- | --- |
| `generate` | `/ai-gitee generate <提示词> [比例]` | 文生图 |
| `style` | `/ai-gitee style <风格> [描述] [比例]` | 风格转换；附带图片则为图生图 |
| `ai-edit` | `/ai-gitee ai-edit <提示词> [id\|style]` | AI 图片编辑，需附带图片，支持多图 |
| `switch-model` | `/ai-gitee switch-model <模型名>` | 运行时切换模型 |
| `text2image` | `/ai-gitee text2image [--type=<类型>]` | 获取模型列表 |
| `help` | `/ai-gitee help` | 帮助信息 |

LLM 工具：`draw_image`（`llm_tools/draw.py`）——供 LLM 自然语言调用生图。

支持比例（`core/config.py:SUPPORTED_RATIOS`）：`1:1, 4:3, 3:4, 3:2, 2:3, 16:9, 9:16`
比例解析规则：提示词末尾空格分隔的合法比例会被提取，否则默认 `1:1`。

风格提示词来自 `commands/style_prompts.json`，新增风格时在 JSON 中追加键值即可，无需改代码。

---

## 5. 关键约定

- **配置**：全部走 `_conf_schema.json`，代码内默认值集中在 `core/config.py`（`DEFAULT_BASE_URL/MODEL/SIZE/...`），不要在业务代码里散落硬编码。
- **多 Key 轮询**：`GiteeAIClient._get_next_api_key()` 按索引轮询；`parse_api_keys` 兼容字符串与列表配置。
- **错误处理**：API 层将 OpenAI 异常转换为中文 `RuntimeError`（认证/限流/500/未知），命令层捕获后回包友好信息。
- **防抖常量**：`DEBOUNCE_SECONDS=10`、`MAX_CACHED_IMAGES=20`、`OPERATION_CACHE_TTL=300`、`CLEANUP_INTERVAL=10`（每 N 次生成触发一次清理）。
- **Debug 日志**：各组件均实现 `debug_log()`，受 `debug_mode` 开关控制，统一前缀如 `[GiteeAIClient]`、`[RateLimiter]`。
- **异步优先**：所有 I/O 使用 async/await，会话与客户端复用（勿在请求内重复创建 ClientSession）。
- **类型与文档**：函数使用类型注解，docstring 遵循 Google 风格（pydocstyle `--convention=google`），中文注释与说明。

---

## 6. 开发环境

```bash
# 1. 克隆
git clone https://github.com/xiaomizhoubaobei/astrbot_plugin_models_ai.git
cd astrbot_plugin_models_ai

# 2. 安装依赖
pip install -r requirements.txt

# 3. 本地联调：将插件放入 AstrBot 的 data/plugins/ 目录，在插件配置中填入 Gitee AI API Key
```

- CNB 云端开发环境由 `.cnb.yml` 定义（预装 vscode、多个 CLI、AstrBot 源码等）。
- 需要在 AstrBot 运行时上下文中测试，`astrbot.api` 相关模块由宿主提供。

---

## 7. 代码质量与提交规范

### 7.1 提交前自检（pre-commit）

仓库配置了 `.pre-commit-config.yaml`，提交前请执行：

```bash
pre-commit install
pre-commit run --all-files
```

包含：`gitleaks`、`shellcheck`、`black`、`flake8`（max-line-length=100，忽略 E203/W503）、`isort`（profile=black）、`mypy`（ignore-missing-imports）、`pydocstyle`（google）、以及基础文件检查。

### 7.2 代码风格

- `black` 格式化，`isort --profile black` 排序 import。
- 行宽上限 100（flake8），类型注解 + Google 风格 docstring。
- 文件结尾保留换行，禁止尾随空格，统一 LF。

### 7.3 Commit 规范（Conventional Commits）

沿用仓库历史风格：`feat` / `fix` / `docs` / `chore` / `refactor` 等，中文描述。
示例：`fix(gpg): 同步 install_gpg_keys.sh 至 MZAPI 规范版本`、`docs: 添加图像分析功能文档`。

### 7.4 分支与 PR

1. Fork / 从 `main` 拉出特性分支。
2. 完成后提交 PR，说明变更点与验证方式。
3. 面向 Issue 自动化的工作流：`issue-killer.yml`、`pr-review.yml`、`pr-review-killer.yml` 等。

---

## 8. CI / 自动化（`.github/workflows/`）

| Workflow | 作用 |
| --- | --- |
| `CodeQL.yml` | 代码安全分析 |
| `security-scan.yml` / `DevSkim.yml` / `secret-scanning.yml` | 安全与密钥扫描 |
| `PythonDependencyAudit.yml` / `dependency-review.yml` | 依赖审计与依赖变更审查 |
| `tfsec.yml` | IaC 安全扫描 |
| `Scorecard.yml` | 供应链安全评分 |
| `inclusiveness-analyzer.yml` | 包容性分析 |
| `issue-killer.yml` / `issue-triage.yml` / `stale.yml` | Issue 自动化 |
| `pr-review.yml` / `pr-review-killer.yml` | PR 审查自动化 |
| `release.yml` | 发布流程 |
| `iflow-cli-assistant.yml` | iFlow CLI 助手 |

`.cnb.yml`：CNB 流水线在 `main` 分支 push 时同步代码到 GitHub 上游仓库。

---

## 9. Agent 工作指引

1. **先读配置再动手**：涉及新配置项时同步更新 `_conf_schema.json` 与 `core/config.py`。
2. **保持分层**：命令逻辑放 `commands/`，可复用能力放 `core/`，上游 API 调用放 `gitee/`，LLM 工具放 `llm_tools/`。
3. **复用基础设施**：防抖统一用 `core/command_utils.check_rate_limit`，比例解析统一用 `parse_prompt_and_size`。
4. **新增指令**：在 `main.py` 的 `ai_gitee_group` 注册，并在 `commands/` 与 `commands/__init__.py` 中实现/导出。
5. **新增风格**：只改 `commands/style_prompts.json`，不写死代码。
6. **提交前**：运行 `pre-commit run --all-files`，确认 black/flake8/mypy 通过。
7. **提交信息**：使用 Conventional Commits 中文描述。
8. **不要把密钥写进代码或文档**；API Key 一律通过插件配置注入。

---

## 10. 参考文档

- `README.md` — 项目介绍与文档导航
- `docs/DEVELOPMENT_GUIDE.md`、`docs/COMPLETE_DEVELOPER_GUIDE.md` — 开发/架构指南
- `docs/FUNCTIONS_OVERVIEW.md` — 完整功能总览
- `docs/IMPLEMENTATION_ROADMAP.md` — 实现路线图
- `CONTRIBUTING.md`、`CODE_OF_CONDUCT.md` — 贡献与社区规范
