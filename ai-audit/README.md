# AI 审计测试示例

本目录提供 **AI 审计（AI 漏洞分流）** 的测试用示例，用于在本仓库上验证
`GitHub Security Lab Taskflow Agent` 框架的 AI 告警分流链路。

> ⚠️ **说明**：本示例为**测试/演示用途**，供你参考如何把文章
> 《借助 GitHub Security Lab Taskflow Agent 的 AI 支持漏洞分流》中的方法论落地到你自己的仓库。
>
> ✅ `alert_triage_example.yaml` 已按官方框架 `doc/GRAMMAR.md` 语法编写并针对本项目（**Python / AstrBot 插件**）适配：
> 使用 `seclab-taskflow-agent` 头部 + `filetype: taskflow`、顶层 `taskflow` key、
> `agents` 引用 personalities、`repeat_prompt`/`over` 批量循环、`run` shell 任务
> 与 `outputs` JSON Schema 校验等标准语法。

---

## 一、这套 AI 审计在做什么

本仓库已配置 `.github/workflows/CodeQL.yml`（CodeQL 静态扫描，workflow 名 `代码质量分析`），它会扫出安全告警。
AI 审计的作用是：用 **LLM + Taskflow Agent** 对这批 CodeQL 告警做**自动分流**，
剔除误报（False Positive），对真实漏洞生成带精确文件/行号引用的报告，并**自动创建
真实 Issue** 供开发跟进修复。

```
CodeQL 扫出安全告警
     │
     ▼
LLM + Taskflow Agent 逐个审计
  ├─ ① 信息收集：调 GitHub API 拿触发事件/权限/上下文
  ├─ ② 审计：剔除误报（攻击者能否触发？是否特权上下文？）
  ├─ ③ 生成漏洞报告（带精确文件+行号引用）
  ├─ ④ 校验：报告不完整/不一致=幻觉，直接驳回
  └─ ⑤ 落地结构化结论：仅对**校验通过(APPROVED)**的告警产出结论 JSON
```

本目录的 `alert_triage_example.yaml` 即对应上面的 5 阶段流程（外加第 0 步拉取告警）。

> 阶段间数据贯通：各审计阶段通过 memcache 以 `alert_number` 为 key 传递上一步结果
> （`_evidence` 取证、`_triage` 判定、`_report` 报告、`_verdict` 校验结论），
> 第 ⑤ 步只会在读到 `_verdict.status == APPROVED` 且 `_report` 存在时才落地结论，
> 下游持令牌的 `publish` job 再用纯 shell（`jq`）**只挑 `status == "APPROVED"` 的条目**建 Issue，结论同时落盘为 `audit-verdicts.json` 留档。
>
> ⚖️ **确定性边界（重要，勿过度宣称）**：`_verdict` 的**内容**由第 ④ 步的 **LLM** 判定（该告警是不是真实漏洞，属模型判断，不保证永远正确）；示例能**确定性保证**的是「结论 → 发文」这段把关属**非智能体门禁**——第 ⑤ 步与 `publish` job 都只认 `status == "APPROVED"` 字段，且二者均为纯 shell（`jq`/`curl`）、**不含任何 LLM 环节**；`publish` 还会**回查权威 CodeQL 告警**核对 `alert_number`/`rule`/`path` 后才建资源。因此准确的表述是「**凡 `_verdict.status` 被写成非 APPROVED、或与本仓库 CodeQL 告警对不上的条目，机制上不可能被创建 Issue**」，而**不是**「被驳回的误报绝无可能被创建」（后者取决于模型判定本身是否可靠）。
> 原「⑥ 知识回流」因无法在创建 Issue 后立即获得人工反馈而被移除（见文末“为什么没有知识回流”）。

> 🔒 **安全设计：审计与创建 Issue 分离（pwn-request 防护）**
> `ai-audit-scheduled.yml` 把流程拆成**两个 job**，中间只以 **artifact（加密后的纯数据）** 传信：
> - `triage` job：**不持有任何仓库写凭据**（无 `GH_PAT`），只在**默认分支**上检出源码
>   （手动触发也不例外，绝不使用 `github.ref`），产出结论文件 `audit-verdicts.json`；
> - `publish` job：**唯一持有 `GH_PAT` 的 job**，**不检出/不执行任何源码**，只消费 artifact 里
>   的结构化结论按白名单字段建 Issue；且建任何资源前会**用只读 API 回查告警来源**
>   （按 `alert_number` 核对 `rule`/`path`），拒绝非本仓库 CodeQL 告警的伪造结论。
>
> 🔐 **artifact 必须加密交接（协调披露的关键）**：`audit-verdicts.json` 里含 `report` 全文、
> `rule`、`path` —— 正是本工作流刻意**不**放进公开 Issue 的未修复漏洞细节。而 Actions artifact
> 会被持久化，且**任何拥有仓库读权限的人都能下载**（公开仓库 = 任何互联网读者）。若明文上传，
> 等于把私密 advisory 里的细节经 artifact 泄成公开可读，彻底架空协调披露设计。
> 因此 `triage` 在上传前用**公钥**做混合加密 + **加密后认证**（encrypt-then-MAC）：
> 数据密钥/MAC 密钥均为**十六进制可打印串**（避免 raw 二进制经 `-pass file:` 被换行截断成空口令），
> 用数据密钥做 AES-256-CBC 加密，再用独立 MAC 密钥对**密文**做 HMAC-SHA256（`openssl enc` 不支持
> AEAD，故用 encrypt-then-MAC 等效达成「篡改即拒绝」），两枚密钥一并经 RSA-OAEP-SHA256 封装；
> **只上传密文 + 封装密钥 + HMAC**。`publish` 用**私钥**（Secret 注入）解出密钥、**先验 HMAC 再解密**
> 后才消费。这既堵住泄漏，又**不削弱「triage 不持仓库写凭据」这道安全墙**——公钥是公开信息，可随仓库提交。

> 之所以必须这样拆：`workflow_run` 会为 **PR（含 fork）触发的 CodeQL 运行**也开火，而 PR 源码
> 由提交者控制；若让持令牌的 job 同时执行 PR 源码，fork 提交者即可借 PR 改写审计模板，
> 驱动 agent 拿高权限 PAT 发文（典型 pwn-request）。因此本工作流还有两道源头门禁：
> ① `triage` job 的 `if` 要求上游运行的 `head_repository` 必须是**本仓库**，fork PR 触发的
> CodeQL 运行一律不进入；② checkout 只认**可信 ref**，绝不用事件携带的 PR head。

> ⚠️ `publish` job 会**真实创建 Issue**。若你只想看分流结果、不修改仓库，
> 请把 `ai-audit-scheduled.yml` 中的 `publish` job 整体注释掉（`triage` 仍会正常产出结论）。

> 💡 **无告警自动跳过**：当仓库当前**没有 open 的 CodeQL 告警**时，
> `alerts` 任务（第 0 步）拉取到的列表为空，后续 5 个 `repeat_prompt` 任务
> 都加了 `if: "outputs.alerts | length > 0"` 条件，会被**整体跳过**（记录为
> skipped），不会对空迭代反复输出 `repeat_prompt iterable is empty!` 噪音，
> 也不会有任何 LLM / Issue 副作用。有告警时行为完全不变。

---

## 二、目录结构

```
ai-audit/
├── README.md                        # 本说明
├── __init__.py                      # 使 ai_audit 成为可导入 Python 包（框架 importlib.resources 必需）
├── alert_triage_example.yaml        # 5 阶段 AI 审计 taskflow（官方 GRAMMAR 语法）
├── model_config.yaml                # OpenAI 兼容上游模型配置（api_type: chat_completions；模型名由环境变量提供）
├── model_config.py                  # [参考] model_config.yaml 的说明文档（框架不读取）
└── personalities/
    ├── __init__.py                  # 使 personalities 成为可导入子包
    └── python_auditer.yaml          # 项目自带的 Python 审计人格（personality）
```

> ⚠️ **为什么必须有 `__init__.py`？** 框架通过
> `importlib.resources.files(package)` 加载 taskflow / personality / model_config，
> 它要求目标目录是**可导入的 Python 包**。因此本目录（复制后名为 `ai_audit`）
> 及其 `personalities/` 子目录都必须包含 `__init__.py`，否则会报
> `No module named 'ai_audit'`。若目录被当作 PEP 420 命名空间包（无 `__init__.py`）
> 处理，在不同 Python 环境 / hatch 环境下不一定能稳定被 `importlib.resources` 解析，
> 显式提供 `__init__.py` 是最稳妥的做法。

**为什么需要自带的 Python 人格？** 官方框架默认自带的安全审计人格是
`seclab_taskflow_agent.personalities.c_auditer`，它是针对 **C 语言**设计的
（系统提示词明确 “Find vulnerabilities in any provided C code”）。
本项目是 **Python**（AstrBot 插件，核心代码在 `main.py` / `core/` / `commands/` /
`gitee/` / `llm_tools/` / `qianwen/`），
为获得正确的审计结果，示例改用项目自带的
`ai_audit.personalities.python_auditer`（面向 Python 的审计人格），
并复用了官方 `codeql` + `memcache` 两个 toolbox。

---

## 三、运行前提（需要你配置）

| 前提 | 说明 | 状态 |
|------|------|------|
| 仓库已开启 CodeQL 扫描 | `.github/workflows/CodeQL.yml` 已存在 | ✅ 已具备 |
| `seclab-taskflow-agent` 框架 | 需部署框架本体 | ❌ 需部署 |
| LLM 模型（支持函数调用） | 任意 OpenAI 兼容上游：DeepSeek / 通义千问 / Moonshot / 本地 vLLM 等 | ❌ 需配置（`AI_API_ENDPOINT` + `AI_API_TOKEN`） |
| GitHub PAT（读告警） | 审计侧只读拉取 CodeQL 告警用（`security_events` 读权限即可） | ❌ 需你提供 |
| GitHub PAT（写 Issue） | 仅 `publish` job 创建真实 Issue 与私密公告用（`issues` 写 + `repository_advisories:write`；细分令牌还需管理员/安全经理角色） | ❌ 需你提供 |
| MCP Server（GitHub API） | 框架可选的信息收集能力（只读） | ⭕ 可选 |

---

## 四、部署与运行

> 框架通过 **Python 模块路径**加载 taskflow / personality（`packagename.filename`）。
> 因此需要把本目录（含 personalities）放到框架能解析到包路径的地方。

### 方式一：复制到框架仓库根目录（推荐，最省事）

1. 部署框架与 taskflows：

> 🔒 **必须固定到与工作流一致的已复核 commit**：`seclab-taskflow-agent` 是要**执行**的框架本体，
> 手工部署时若直接 `git clone` 默认分支，等于运行一个**会漂移的 HEAD**——上游任意一次提交都会
> 悄悄改变即将以你的仓库凭据（PAT / LLM Key）执行的代码，也可能悄然破坏本文档描述的 taskflow 行为。
> 因此这里**与你仓库中 `.github/workflows/ai-audit-scheduled.yml` 保持一致**，把框架 checkout 到
> 同一枚已复核的发布 commit `6038bb4ee9661887a09215eac70fccceb396cd02`（即 `v0.5.0`）。

```bash
# 克隆后显式 checkout 到已复核的发布 commit SHA（勿停留在漂移的默认分支）
git clone https://github.com/GitHubSecurityLab/seclab-taskflow-agent
cd seclab-taskflow-agent
git checkout 6038bb4ee9661887a09215eac70fccceb396cd02   # v0.5.0，与 ai-audit-scheduled.yml 一致

# seclab-taskflows 仅作官方 taskflow 范例参考（本示例不使用其中任何文件），
# 若需查阅同样建议固定到对应发布 tag/commit，避免拿到漂移的默认分支。
git clone https://github.com/GitHubSecurityLab/seclab-taskflows
```

> ⚠️ **一致性要求**：升级框架时请**同时**修改本处与 `ai-audit-scheduled.yml` 中的
> `ref: <commit-sha>`，保证手工运行与 CI 运行执行的是**同一份**已复核代码；
> 只改一边会造成「文档描述的版本」与「实际执行的版本」悄悄分叉（本条即为此前遗留的分叉）。

2. 把本目录复制到框架仓库**根目录**，**目录名使用下划线 `ai_audit`**（模块路径不能用连字符）：

```bash
# 从本项目仓库复制到框架仓库根目录
cp -r <本项目>/ai-audit ai_audit
# 得到 ai_audit/alert_triage_example.yaml
#       ai_audit/personalities/python_auditer.yaml
```

> ⚠️ **为什么是根目录而不是 `examples/`？** 框架通过
> `importlib.resources.files(package)` 按 **Python 模块路径**加载，而运行命令使用
> `-t ai_audit.alert_triage_example` / `-m ai_audit.model_config` 引用**顶层模块
> `ai_audit`**。因此目录必须放到框架仓库根目录（该目录在 `sys.path` 上）使其可作为
> `ai_audit` 导入；如果放进 `examples/`，会变成 `examples.ai_audit`，模块路径对不上。

3. 按官方配置指南配好 LLM 模型 + GitHub PAT + MCP Server。
   示例的 `alerts` 任务会通过 GitHub Code Scanning API 拉取**最新 CodeQL 告警**，
   因此需要导出 `GITHUB_TOKEN`（PAT，需含 `security_events` 读权限）。
   仓库统一由 `globals.repo`（owner/repo）这一个值决定：**告警拉取、memcache 状态 key
   都基于它**，workflow 通过 `-g repo=...` 把实际仓库注入进来（见下文 GitHub Actions 说明），
   因此不再需要、也不应单独设置 `GITHUB_REPOSITORY` 以免与 `globals.repo` 分裂。

   > 各审计阶段经 memcache 按告警贯通：第 ① 步写取证 `_evidence`，第 ② 步写判定 `_triage`，
   > 第 ③ 步对 TP 写报告 `_report`，第 ④ 步写校验结论 `_verdict`（APPROVED/REJECTED，
   > 且**自包含** `alert_number/rule/path/status/reason/report`，供第 ⑤ 步直接消费）。
   > 其中第 ④ 步校验**必须同时读取 `_report` 与 `_evidence`**，基于取证核对报告的文件/行号；
   > 若 `_evidence` 缺失则一律驳回（`no_evidence`），避免放行未经验证的行号。
   > 第 ⑤ 步（**纯 shell**）**仅当 status==APPROVED 且报告非空**时，把
   > `{alert_number, rule, path, status, report}` 追加写进 `AUDIT_VERDICT_FILE`
   > （默认 `/tmp/audit-verdicts.json`）。
   >
   > ⚠️ **第 ⑤ 步的写法有硬约束（本示例最容易踩的坑，勿改回去）**：框架只把 MCP 工具
   > 暴露给**智能体任务**，纯 shell 任务里 `memcache_get_state` / `memcache_set_state`
   > **不是可执行命令**，调用只会 `command not found`（再被 `2>/dev/null || true` 吞掉）
   > → `_STATUS` 恒为空 → 恒判 SKIP → **每条告警被静默跳过、全量漏审**。
   > 此外两条同源约束：**shell 任务不参与 `repeat_prompt` 扇出**（框架 `fans_out` 恒为
   > false，`run:` 只执行一次），且 **`run:` 字段不会被框架做 Jinja 渲染**（只渲染
   > `user_prompt`），故 `{{ result.* }}` / `{{ globals.* }}` 在 shell 里都是死字面量。
   > 因此第 ⑤ 步改为：**脚本自行按框架同一套规则解析 memcache 落盘目录（
   > `MEMCACHE_STATE_DIR` 或 platformdirs 默认路径）、直接读 `memory.db`/`memory.json`**，
   > 再对第 ④ 步写入的**自包含** `_verdict`（含 `alert_number/rule/path/status/report`）
   > 做确定性过滤——全程不调用 MCP、不依赖模板渲染。
   >
   > 📌 **落盘文件名与表名以「上游框架实际 schema」为准（勿凭印象猜）**：
   > 默认后端 `sqlite` 落 `memory.db`（**不是** `memcache.db`，见 upstream
   > `memcache_backend/sqlite.py`）；其建表模型 `KeyValue` 的 `__tablename__` 是
   > **`key_value_store`**（见 upstream `sql_models.py`），故查询必须写
   > `SELECT key, value FROM key_value_store`——写成 `key_value` 会抛
   > `no such table`，在本步 `set -e` 下直接失败、不产出任何结论。
   >
   > 🔒 **本 taskflow 全程不创建 Issue、不需要 `GH_PAT`**：它只产出结论文件。
   > 真正的 Issue 创建交给 `ai-audit-scheduled.yml` 里持令牌的独立 `publish` job，
   > 由它消费该结论文件后完成——这样「不可信输入（告警/仓库内容）」与「高权限动作（建 Issue）」
   > 分处两个 job，杜绝 fork PR 借审计链拿高权限令牌（见上文安全设计）。
   >
   > ⚖️ **边界澄清（勿过度宣称）**：`_verdict` 的**内容**（某告警到底算不算真实漏洞）
   > 是第 ④ 步由 **LLM** 判定的，属模型判断，**不保证**永远正确。本示例能确定性保证的是
   > **「结论 → 发文」这一段被非智能体门禁把控**：第 ⑤ 步与 `publish` job 都只看
   > `status == "APPROVED"` 这一字段，且两者均为纯 shell（`jq`/`curl`）、**不含任何 LLM 环节**。
   > 换言之，**一旦某告警的 `_verdict.status` 不是 APPROVED，它就无法进入建 Issue 路径**——
   > 这是被硬编码的过滤所强制的；但「判定该告警是否 APPROVED」本身仍是模型输出的判断，
   > 因此**不能**宣称「被驳斥的误报绝无可能被创建」，只能说「被写入 REJECTED 的告警不可能被创建」。

4. 运行（注意模块路径前缀 `ai_audit.`，并通过 `-m` 显式指定模型配置）：

```bash
# 方式 A：仅设环境变量（端点与密钥来自 AI_API_ENDPOINT / AI_API_TOKEN，模型用框架默认）
AI_API_ENDPOINT=https://api.deepseek.com/v1 \
AI_API_TOKEN=<你的APIKey> \
GITHUB_TOKEN=<只读 PAT，含 security_events 读权限即可> \
hatch run main -t ai_audit.alert_triage_example

# 方式 B：显式指定 model_config（推荐，声明 api_type: chat_completions，更稳）
# 模型名由环境变量 COPILOT_DEFAULT_MODEL 提供（免改代码即可切换模型）
COPILOT_DEFAULT_MODEL=<你的模型名，如 deepseek-v4-flash> \
AI_API_ENDPOINT=https://api.deepseek.com/v1 \
AI_API_TOKEN=<你的APIKey> \
GITHUB_TOKEN=<只读 PAT，含 security_events 读权限即可> \
hatch run main -t ai_audit.alert_triage_example \
    -m ai_audit.model_config
# 结论落在 $AUDIT_VERDICT_FILE（默认 /tmp/audit-verdicts.json），本命令不创建 Issue
```

> `model_config.yaml` 是框架实际读取的模型配置文件（`-m` 参数指定模块路径，
> 框架自动追加 `.yaml` 后缀查找）。`endpoint`/`token` 由环境变量
> `AI_API_ENDPOINT`/`AI_API_TOKEN` 提供，密钥不会硬编码进仓库。
> **模型名不再写死在 `model_config.yaml` 中**，而是由框架在运行时读取环境变量
> `COPILOT_DEFAULT_MODEL` 决定，因此修改模型只需改环境变量 / 仓库 Secret
> （见下方 `AI_MODEL_NAME`），而无需改动本仓库代码。

#### 用 GitHub Actions 自动运行（推荐）

本仓库已内置 `.github/workflows/ai-audit-scheduled.yml`，可直接自动（或手动）运行 AI 审计：

- **自动触发**：默认监听 `CodeQL.yml`（name: `代码质量分析`）的 `completed` 事件，
  在 CodeQL 扫完后确定性地运行，保证消费最新告警；同时保留 `workflow_dispatch` 手动触发。
  🔒 **fork 门禁**：仅当上游运行的 `head_repository` 为本仓库时才进入审计，fork PR 触发的
  CodeQL 运行一律跳过，从源头杜绝把 PR 源码当作不可信输入送进审计链。
- **手动触发**：在仓库 **Actions → AI 审计（CodeQL 完成后自动分流）→ Run workflow** 手动跑一次用于验证。
  🔒 手动触发有两道闸：① 仅在**默认分支**上放行，且 checkout 的 ref **固定为默认分支**
  （不用 `github.ref`），故手选其它分支也不会把未审分支的源码送进审计链；
  ② `publish` job 绑定受保护 `environment`（`ai-audit-publish`，需配 required reviewers），
  持令牌发文会**暂停等待人工审批**。
  ⚠️ 部署前请在 **Settings → Environments** 建好同名环境并配置审批人，否则 `publish` 会因
  环境不存在而失败。

**所需 Secrets**（仓库 **Settings → Secrets and variables → Actions**）：

| Secret | 必填 | 用途 |
|--------|------|------|
| `AI_API_ENDPOINT` | ✅ | 上游 base_url（OpenAI 兼容口，如 `https://api.deepseek.com/v1`，或本地 vLLM / Ollama 的 OpenAI 兼容地址） |
| `AI_API_TOKEN` | ✅ | 对应厂商的 API Key（需支持函数调用） |
| `AI_MODEL_NAME` | ✅ | 实际调用的模型名（如 `deepseek-v4-flash` / `qwen-max` / `kimi-k2` 等）。工作流运行时将其透传给框架的 `COPILOT_DEFAULT_MODEL` 环境变量 |
| `GH_PAT` | ✅ | GitHub PAT。需同时具备：`security_events` 读（读 CodeQL 告警）、`issues` 写（建公开 Issue）、**`repository_advisories:write`**（建私密安全公告）。细分令牌需**同时持有该权限与仓库管理员/安全经理角色**，或改用 classic PAT（`repo` scope 且账号为管理员/安全经理）。**仅注入 `publish` job**，`triage` job 绝不接触该 Secret |
| `AUDIT_HANDOFF_PRIVATE_KEY` | ✅ | 与仓库内 `ai-audit/handoff-public-key.pem` **配对的 RSA 私钥**（PEM 全文，见下方「加密交接」）。**仅注入 `publish` job** 用于解密；`triage` 只用公钥，不接触私钥 |
| `MCP_CONFIG` | 可选 | MCP Server（GitHub API）配置 |

> 📌 框架只识别 `AI_API_ENDPOINT` / `AI_API_TOKEN`（即 `AsyncOpenAI(base_url=..., api_key=...)`），
> 不读取 `OPENAI_API_KEY` / `OPENAI_MODEL`。模型名通过环境变量 `COPILOT_DEFAULT_MODEL` 提供
> （由仓库 Secret `AI_MODEL_NAME` 透传），`model_config.yaml`（`-m ai_audit.model_config`）仅声明
> `api_type: chat_completions`（OpenAI 兼容标准协议）。

> ⚠️ 由于示例会为真实漏洞**创建 Issue**，`GH_PAT` 必须具有仓库的 `issues` 写权限，
> 否则 `publish` job 会失败（可把 `publish` job 整体注释掉，降级为只产出审计结论）。
> 🔒 `GH_PAT` 只在 `publish` job 的建 Issue 步骤注入；`triage` job 全程不接触它，
> 因此即便审计对象被污染，也无凭据可被滥用。

> 首次使用建议先 `workflow_dispatch` 手动跑一次，确认链路正常后再依赖自动触发。

#### 加密交接：生成密钥对并注入私钥

`triage` → `publish` 之间以 artifact 传信，且 artifact 对**任何有读权限的人**可下载，
故必须**加密交接**。做法是「公钥随仓库提交、私钥只进 Secret」：

```bash
# 1) 生成 RSA 密钥对（3072 位；私钥保密，公钥公开）
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out handoff-private.pem
openssl rsa -in handoff-private.pem -pubout -out handoff-public.pem

# 2) 用你的公钥替换仓库内占位公钥，并提交
cp handoff-public.pem ai-audit/handoff-public-key.pem
git add ai-audit/handoff-public-key.pem && git commit -m "chore(ai-audit): 更新加密交接公钥"

# 3) 把【私钥全文】设为仓库 Secret：Settings → Secrets and variables → Actions →
#    新建 AUDIT_HANDOFF_PRIVATE_KEY，粘贴 handoff-private.pem 全文
# 4) 私钥用完即删（绝不入库）
shred -u handoff-private.pem 2>/dev/null || rm -f handoff-private.pem
```

- 🔐 **公钥可以公开**（它只能加密，不能解密），因此 `triage` 读它**无需任何 Secret**，
  「triage 不持仓库写凭据」的安全墙得以保持（它仍需调用 LLM 的 `AI_API_TOKEN` 与只读
  `GITHUB_TOKEN`，但这些都不具备仓库写能力）。
- 🔑 **私钥只能经 Secret 注入**，且**只注入 `publish` job**；严禁写进仓库、日志或评论。
- ♻️ **轮换**：公钥（入库）与私钥（Secret）是**分两步更新**的，中间存在窗口期——
  若此刻恰好有 workflow 正在跑，它会用「**旧公钥加密、新私钥解密**」而无法解开，导致发布失败。
  因此正确顺序是：**先暂停触发并等待现有运行完成** → 再更新仓库公钥 → 再更新 Secret 私钥 →
  **验证新密钥配对**（跑一次成功解密）→ 恢复触发。旧密文因留存期短（`retention-days: 7`）
  会自然过期。
- 若 `AUDIT_HANDOFF_PRIVATE_KEY` 未配置，`publish` job 会**明确失败**（而非降级为明文放行）——
  但仅在**确有待发布结论**时如此，见下方「空结论短路」。
- 🔏 **完整性**：`triage` 侧在加密后对密文再做 HMAC-SHA256（encrypt-then-MAC），
  `publish` 侧**先验 HMAC 再解密**——密文被篡改即拒绝，不以「是不是 JSON 数组」充当完整性校验。

#### 空结论短路：无 APPROVED 结论时不再误报为失败

判空短路位于 `publish` job 的**「解密前短路（无待发布结论则跳过，不触碰私钥）」**步骤，
排在**解密步骤之前**（即 job 内第 3 步，见 `ai-audit-scheduled.yml` 的 `publish.steps`；
解密本身是第 4 步）。判据是 triage 侧显式外化的**空结论标记**：

```
publish 侧：/tmp/audit/audit-verdicts.empty 存在
        →  直接跳过解密与发文（skip=true，不触碰私钥）

triage 侧：jq 'length' == 0
        →  只产出 audit-verdicts.empty 标记，**不加密、不上传任何密文**
        （有内容时则相反：只上传密文三件套，不产出标记）
```

> ⚠️ **口径要点**：这里的 `jq 'length'` 统计的是**待发布的 APPROVED 结论条数**，
> 而**不是** CodeQL 告警条数。二者并不等价——一次运行**可能扫到若干告警、却没有任何一条
> 被判为 APPROVED**（例如全被判为误报而 `REJECTED`）。因此本短路的准确语义是
> **「无 APPROVED 结论」**，不能表述为「零告警」：后者会让人误以为「只有告警数为 0 才会
> 触发短路」，进而在「有告警但全被驳回」时对短路行为感到困惑。

- **为什么需要**：`triage` 在**无 APPROVED 结论**时也会正常收尾（兜底把 `/tmp/audit-verdicts.json`
  写成 `[]`）。若「先加密上传、再在 publish 侧先解密再判空」，一条空结论也会去撞
  `AUDIT_HANDOFF_PRIVATE_KEY`：首次部署尚未配密钥时，`publish` 会在**毫无可发布内容**的情况下硬失败，
  表现为「CodeQL 跑完 → AI 审计红了」，容易被误诊为链路故障。
- **两条分支互斥、判据明确**：无 APPROVED 结论时 artifact 内**只有** `audit-verdicts.empty`、**没有任何密文**，
  有内容时**只有**密文三件套、没有标记——`publish` 只认这枚标记（另保留「既无标记又无密文」
  的兜底短路，兼容旧产物）。因此无 APPROVED 结论的运行**无需私钥**，与 `Secret` 是否配置完全解耦。
- **安全边界不变**：短路只看「有没有待发布内容」，**不解析密文、不放宽任何完整性要求**；
  一旦确有密文需要解密，仍严格走「密钥配对自检 → 验 HMAC → 解密 → 数组格式校验」。
- **两条路径的差异只体现在「有无内容可发」**：无内容时跳过，有内容时该失败照旧失败
  （密钥缺失/错配仍是明确失败，绝不降级为明文放行）。

#### 首次部署的推荐顺序

密钥是「公钥入库 + 私钥进 Secret」**成对**生效的，只做一半必然解密失败。推荐：

1. 生成密钥对（见上一小节），**公钥提交入库、私钥存 Secret**；
2. 先在本地做一次配对自检（见下），确认公私钥同源；
3. 再跑一次 `workflow_dispatch` 验证整条链路。

> 💡 **配对自检**（无需跑整条流水线）：用公钥加密一段探针、再用私钥解回，
> 能解回即说明配对正确：
> ```bash
> # ⚠️ 必须 `set -e`（或显式检查解密退出码）：末尾的 `shred` 是清理命令，
> #    若不开启 `-e`，它会**掩盖** `openssl pkeyutl -decrypt` 的非零退出状态——
> #    即使解密失败（公私钥不配对），脚本整体仍会「成功」返回，自检形同虚设。
> set -euo pipefail
> # ⚠️ 私钥一律经 `mktemp` 落到**私有**临时文件（默认 0600、随机名）：
> #    · 不能写固定路径（如 `/tmp/priv.pem`）——`/tmp` 是全局可写的共享目录，
> #      固定名既会被他人**预置符号链接**（重定向**跟随链接**写到别处），
> #      也会**覆盖**别人放在同名路径上的文件；`mktemp` 的随机名 + `O_EXCL`
> #      创建从根上杜绝这两种「可预测路径」攻击。
> #    · 不能依赖默认 `umask`——常见 `umask 022` 下重定向出的文件是 **0644 全局可读**，
> #      明文私钥落成全局可读等于直接泄漏；`mktemp` 创建的却是 0600（仅属主可读）。
> #    两条合起来才成立：随机名挡「符号链接/覆盖」，0600 挡「被读取」。
> # ⚠️ 仍要挂 `EXIT` 清理钩子：`set -e` 下**任何**中途失败都会直接退出，
> #    绝无机会走到末尾的 `shred`——钩子负责在任意退出路径（成功/失败/被信号打断）
> #    删除探针与私钥，并**原样保留**退出码，既不掩盖失败、也不留残骸。
> #    （钩子只缩短暴露窗口；防读取/防覆盖由上面的 `mktemp` 负责，二者缺一不可。）
> PRIV="$(mktemp)"; PROBE="$(mktemp)"; PROBE_ENC="$(mktemp)"; rm -f "$PROBE_ENC"
> cleanup() {
>   rc=$?
>   shred -u "$PRIV" "$PROBE" "$PROBE_ENC" 2>/dev/null || rm -f "$PRIV" "$PROBE" "$PROBE_ENC"
>   return "$rc"
> }
> trap cleanup EXIT
> printf 'probe' > "$PROBE"
> openssl pkeyutl -encrypt -pubin -inkey ai-audit/handoff-public-key.pem \
>   -in "$PROBE" -out "$PROBE_ENC" -pkeyopt rsa_padding_mode:oaep -pkeyopt rsa_oaep_md:sha256
> # 私钥经变量从 stdin 写入（不把 Secret 放进命令行，避免进程列表泄漏）；
> # 落盘文件由 mktemp 创建，权限已是 0600，无需再赌环境 umask。
> printf '%s' "$AUDIT_HANDOFF_PRIVATE_KEY" > "$PRIV"
> # 解密失败即中止（`set -e` 生效），此时由上面的 EXIT 钩子收尾清理、不留私钥残骸
> openssl pkeyutl -decrypt -inkey "$PRIV" -in "$PROBE_ENC" \
>   -pkeyopt rsa_padding_mode:oaep -pkeyopt rsa_oaep_md:sha256
> echo "✅ 配对自检通过：公私钥同源"
> ```

#### 排错对照

| 现象 | 含义 | 处置 |
|------|------|------|
| 报「缺少仓库 Secret `AUDIT_HANDOFF_PRIVATE_KEY`」 | 私钥未配（或配了空值）**且确有待发布结论** | 按提示生成密钥对并配置 Secret；无待发布内容时该步会**自动跳过**，不再报错 |
| 报「私钥无法解开封装密钥：密钥不配对」 | Secret 里的私钥与仓库公钥**不是同一对** | 重新生成一对，**公钥入库 + 私钥进 Secret 两步都做**，再做一次配对自检 |
| 报「HMAC 校验失败」 | 密文被篡改，或拿的是**不该用的旧密文** | 确认 artifact 未经修改；必要时重跑上游 `triage` 重新产出密文 |
| 无任何报错但**本次运行**没建新 Issue | ⚠️ **两种成因**，别急着归咎 `_verdict`：①**幂等去重命中**——该告警此前已建过 Issue（按 `alert_number` 指纹去重），本次属**正常跳过**；②结论里确实没有 `status == APPROVED` 的条目 | **先查去重、再查门禁**：按 `<!-- ai-audit-alert:<alert_number> -->` 指纹或标题 `[AI审计] CodeQL 告警 #<alert_number>` **检索**是否已有 open Issue（去重会**逐页遍历全部 open Issue**，不要只看首页）——**已存在 = ①，属预期**；确认无既有 Issue，才是②，再去查 triage 阶段的 `_verdict` 判定理由 |
| 无 APPROVED 结论时 `publish` 仍报「缺少 Secret」 | 判空短路**未生效**（应表现为跳过、不报错） | 检查 `publish` 短路步骤是否**排在解密之前**、且识别 `audit-verdicts.empty` 标记；再看 triage 是否在 `jq 'length' == 0` 时**未上传任何密文**（若仍上传了 `.enc`，说明 triage 侧判空步骤缺失或被跳过） |

### 方式二：把 `ai_audit` 作为可导入包安装

如果你更希望像普通包一样使用，把 `ai-audit` 目录命名为 `ai_audit` 并安装进 Python 环境，
使其可通过 `ai_audit.personalities.python_auditer` 解析，然后把
`alert_triage_example.yaml` 中的 agents 引用改为
`ai_audit.personalities.python_auditer` 即可。

---

## 五、先在一个告警验证

先在一个 CodeQL 告警上跑通，验证链路后再铺开到全部告警：

1. 示例开头 `alerts` 任务已改为从 GitHub Code Scanning API 拉取**最新 CodeQL 告警**
   （`state=open&tool_name=CodeQL`），并映射成下游需要的
   `alert_number / rule / path / message` 结构，无需手动维护告警列表。
2. 观察各阶段输出是否符合预期，重点看**校验阶段（第 ④ 步）**是否把不完整报告驳回并写入
   `_verdict.status == REJECTED`，以及第 ⑤ 步的结论文件是否只包含 APPROVED 的告警。
3. 确认无误后开启 `publish` job（若已注释），即可对真实漏洞自动创建 Issue。

---

## 六、本示例的特点

- **针对 Python**：适配本仓库（AstrBot Python 插件）的代码审计场景。
- **5 阶段审计链 + 数据贯通**：信息收集 → 审计 → 报告 → 校验 → 落地结构化结论。
  第 ①~④ 步（智能体）经 memcache 按告警传递 `_evidence/_triage/_report/_verdict`，
  下游始终基于上游结论判定；第 ⑤ 步（纯 shell）**直接读 memcache 落盘文件**完成确定性过滤
  （不能在 shell 里调 MCP 工具、也不能用 `{{ result.* }}`，详见第三节）。
- **分页拉取**：`alerts` 任务逐页拉取全部 open 的 CodeQL 告警，仓库告警超过 100 条也不会漏审。
- **防幻觉校验**：报告不完整/不一致直接驳回（`_verdict=REJECTED`），避免 LLM 编造漏洞。
- **审计与发文隔离**：taskflow 只产出结论文件；Issue 由独立持令牌 job 消费结论创建。
  为遵守协调披露，公开 Issue 仅作**脱敏占位**：
  - **标题**：`[AI审计] CodeQL 告警 #<alert_number>`（**不含** rule/path）；
  - **标签**：仅 `security` 与 `ai-audit`（**没有** `bug`）；
  - **正文**：只有告警编号 + 「私密详情见 security advisory `<ghsa_id>`」+ 处置约定，
    rule / path / report 全文一律不放公开渠道，而是写进**私密 security advisory**。
  且仅对 `_verdict.status == APPROVED` 的告警执行——不可信输入与高权限动作分处两个 job。
  ⚖️ 注意边界：**「结论 → 发文」的把关是非智能体的确定性 shell 门禁**（只认 APPROVED 字段、
  无 LLM 参与），但 **`_verdict` 本身是 LLM 判定**。故此处只能承诺「非 APPROVED 的告警不会
  被创建 Issue」，**不能**承诺「模型判定错误（误报被误判为 TP/APPROVED）也不会被创建」。
- **发文幂等 + 并发自愈（防重复 Issue）**：CodeQL 在 push / PR / schedule 多入口下可能
  **并发完成**，从而同时拉起多个本工作流实例；若两个 `publish` 同时走到「先查是否存在、
  再创建」的判定点，就会双双读到「不存在」→ 双双创建 → 同一漏洞出现两条 Issue。为此：
  1. **工作流级 `concurrency`**：`group: ${{ github.workflow }}` + `cancel-in-progress: false`
     + `queue: max`，把所有触发源的实例收敛到**同一条队列**串行执行，从源头掐掉并发
     （不掺 `github.ref`，否则不同 ref 的实例会落入不同队列、竞态依旧；仅设
     `cancel-in-progress: false` 会「替换待跑实例」，需 `queue: max` 才真正**排队不丢单**）。
  2. **指纹去重**：正文首部写入 `<!-- ai-audit-alert:<alert_number> -->`（HTML 注释，用户不可见），
     以 **`alert_number`** 而非标题作幂等判据——标题是 `[AI审计] CodeQL 告警 #<alert_number>`，
     单靠标题匹配易漏判/误判；告警编号是唯一稳定锚点。私密公告同样按**完整标题精确相等**
     去重（不可用 `contains`，否则 `#1` 会误命中 `#10`）。
  3. **全量翻页**：去重检索**逐页遍历全部 open Issue**，而非只取 `?per_page=100` 首页——
     仓库 open Issue 超 100 条时，排在其后的既有 Issue 会被漏查而重复创建。
  4. **创建后自愈（TOCTOU 兜底）**：创建后立即复查同指纹；若临界区里对方已抢先建过，
     则按「保留编号最小（最早创建）」的确定性规则**自动关闭本条**，收敛到唯一一条 open Issue，
     无需人工清理。即便 `concurrency` 被误删或平台偶发重放，也能自愈。
  > 说明：`concurrency` 是第一道闸（防并发发生），指纹 + 翻页 + 自愈是第二道闸（并发若发生也能收敛），
  > 二者构成纵深防御。

---

## 七、为什么移除了“知识回流”这一阶段

原第 ⑥ 步“把人工驳回原因回流给 LLM”紧跟创建 Issue 之后运行，但此刻**人类评审尚未介入**，
既读不到真实驳回原因、也没有持久化落点，只能产出一个孤立回复，并不能形成所宣称的学习闭环。

人工反馈（对 Issue 打“误报/已修复”标签、关闭原因、评论）属于**事后事件**，应由独立的事件驱动
工作流（如监听 `issues` 的 `labeled`/`closed` 事件）在 Issue 被人工处理后异步摄入并持久化，
供下一次审计前载入知识库。若你需要该能力，请另建反馈工作流。

---

> 🔒 安全模型说明：本工作流已按「不可信输入与高权限动作隔离」原则改造——审计 job
> **不持有任何仓库写凭据**（它仍需 `GH_PAT` 之外的 `AI_API_TOKEN` 调用 LLM、
> 以及一枚**只读** `GITHUB_TOKEN` 读告警，因此准确说法是「无仓库写凭据」而**不是**「无凭据」）、
> 发文 job 不落地源码，两者以 artifact 传信，并在 `workflow_run` 上加了 fork 门禁，
> 用于消除「fork PR 源码 → 持 GH_PAT 的 AI agent」这一提权路径。
>
> 📌 本示例由 CNB NPC（武则天）依据 `XMZZUZHI/Github/302/prompt_generator` 仓库的 ai-audit 示例，
> 为本仓库 `astrbot_plugin_models_ai`（Python）适配生成的测试用示例，
> 供你评估 AI 审计链路。请结合你的实际业务代码调整审计规则。
