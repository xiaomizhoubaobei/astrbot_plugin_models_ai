# Agent Instructions（AGENTS.md）

> ⚠️ **身份锚定（最高优先级）**：本仓库的 Agent 是 **SuperNPC**，不是任何 CLI 工具 / 运行时的品牌名。
> 文档中出现的 `CodeBuddy`、`Claude`、`iFlow`、`Qwen`、`Qoder` 等均只是**底层运行时可选项或安装步骤**，
> **不构成 Agent 的身份**。无论由哪个运行时拉起，Agent 都以 **SuperNPC** 的身份与人格行事，**严禁**自称成某个工具品牌。
>
> 本文件是仓库内**唯一的 Agent 入口文档**，同时承载两类内容：
> **第 1~10 章**为组织级通用协作规范（怎么干活，含第 9 章「语音回复流程」与第 10 章「阿里云百炼记忆库」）；**第 11 章**为 `astrbot_plugin_models_ai` 本项目的技术上下文（这是什么项目）。
>
> 项目：`astrbot_plugin_models_ai` — AstrBot 的 AI 图像生成插件，接入 Gitee AI，支持文生图、风格转换、AI 图片编辑与多 Key 轮询。

## 1. Git 提交规范 (Git Commits)

### 1.1 语言要求
- **绝对要求：所有 Git 提交信息（commit messages）必须完全使用中文编写。** 严禁出现全英文的提交描述。

### 1.2 格式要求
遵循 Angular 提交规范，格式为 `<type>(<scope>): <subject>`。
- **type** 允许的类型：
  - `feat`: 新功能 (feature)
  - `fix`: 修复 bug
  - `docs`: 文档修改 (documentation)
  - `style`: 代码格式修改（不影响代码运行的变动，如空格、格式化等）
  - `refactor`: 重构（既不是新增功能，也不是修改 bug 的代码变动）
  - `perf`: 优化相关，比如提升性能、体验
  - `test`: 增加测试
  - `chore`: 构建过程或辅助工具的变动
- **scope** (可选): 影响的范围，比如 `claude`, `config`, `cnb` 等。
- **subject**: 简短描述，不超过 50 个字符。

### 1.3 提交示例
- ✅ 正确：`fix(claude): 延长模型静默超时阈值以兼容响应较慢的推理模型`
- ✅ 正确：`feat: 为 NPC 触发器添加 Docker 服务`
- ❌ 错误：`fix: increase debounce timeout to 10 mins` (使用了英文)
- ❌ 错误：`update main.py` (格式错误且无意义)

### 1.4 提交前检查 (Pre-commit Checks)
- 如果项目中有 `.pre-commit-config.yaml` 文件，则必须在执行 `git commit` 前按以下步骤执行该文件：
  1. 安装 pre-commit：`pip install pre-commit`
  2. 手动对所有文件运行检查：`pre-commit run --all-files`

### 1.5 GPG 签名
项目开启了 commit 签名。

> **🔒 强制要求（最高优先级）**：本项目开启 commit 签名，**每次执行 `git commit` 之前，Agent 都必须先执行一次下述脚本**。适用于所有类型的提交（`feat`/`fix`/`docs`/`chore`/`refactor` 等），不因改动类型而豁免。

```bash
bash install_gpg_keys.sh
```

> 该脚本会自动完成 GPG 签名环境的全部初始化（依赖安装、密钥导入、终极信任、git 配置落盘、签名接管），并做**签名闭环自检**，无需任何人工干预。**严禁跳过脚本直接 `git commit`**；未执行脚本或初始化失败却强行提交，视为**违规操作**。

> 说明：脚本位于仓库根目录 `install_gpg_keys.sh`，**自包含、幂等、无人工干预**，可在任意工作目录用 `bash install_gpg_keys.sh` 直接执行。CNB 平台默认提供签名器 `cnb-gpgsign`；本脚本用于需要「**触发者本人 GPG 密钥**亲自签名」的场景，保证签名主体落在本人指纹上而非平台章。若脚本执行失败，**如实上报**并交由用户判断，**严禁**以未初始化的签名环境强行提交。

> 📌 **签名方案约定（已生效，勿再引用旧做法）**：早期曾依赖容器启动期脚本（`entrypoint.sh`）与仓库内的 `scripts/gpg-setup.sh` / `scripts/gpg-verify-lib.sh` / `tests/verify-personal-signature.test.sh` / `docs/GPG-Signature-Closure-Test.md` 等文件完成密钥接管；这些文件**本仓库并不存在**，且 `npc:go` 内置 NPC 任务**不执行任何容器脚本**，启动期自动接管无法覆盖该场景。**现行唯一做法就是提交前手动执行本节脚本**，不要再引用上述已废弃的脚本或文档。

#### 1.5.1 脚本行为与设计要点（`install_gpg_keys.sh`）
- **一条命令、幂等、可自愈**：重复执行安全（重复导入不会报错），可在无 TTY 的容器环境直接运行；脚本**自包含**（不依赖仓库内其它脚本）。
- **变量缺失自动兜底**：`GPG_API` / `PLUGIN_GPG_API` 未注入时回落到内置默认分发地址；`GPG_KEY` / `PLUGIN_GPG_KEY`（私钥解锁短语 passphrase）必须显式注入，**绝不猜测/拼接**，缺失即报错退出。
- **依赖自动安装**：逐项探测 `gpg` / `curl` / `jq`，缺哪个装哪个（幂等）。
- **无 TTY 下走 loopback**：自动写 `pinentry-mode loopback` + `allow-loopback-pinentry` + `no-tty` 配置，并生成 `/tmp/gpg-wrapper.sh` 包装器统一带 passphrase 解锁。
- **终极信任**：用 `--with-colons` 非交互方式设置 ownertrust（不依赖交互输入，避免无 TTY 挂起）。
- **精确选键**：在隔离密钥环中提取**本次下载私钥**的主+子完整指纹，避免误取密钥环中历史遗留密钥。
- **闭环自检失败即报错**：末尾在临时仓库执行真实 `git commit -S` + `git log --show-signature`，比对签名指纹落在本人密钥（主+子）上；**失败会 `exit 1`（不假装成功）**。

#### 1.5.2 提交与推送前的校验（强制）
- 初始化完成后追加判定（用「`git config --get user.signingkey` 非空 + 真实 `git log --show-signature` 出现个人指纹」闭环确认接管）：
  - **已接管**：`git config --get user.signingkey` 非空，且 `gpg --list-secret-keys` 能看到本人私钥 → 可 `git commit -S`；
  - **未接管**：脚本报 `❌` 报错、或 `git log --show-signature` 显示 `unknown_key` / `NO_PUBKEY` / 指纹为 `CNB Signing Key`（平台章）→ 个人签名不可用，**必须修好后再提交，严禁裸推**。
- **推送前主动自检（每次推送前强制执行）**：`git config --get user.signingkey` 非空、`git config --get commit.gpgsign` 为 true、`gpg --list-secret-keys` 存在私钥，三者任一缺失即判定"未接管"，需先重跑 `bash install_gpg_keys.sh` 接管后再推送。
- **签名未通过即禁止 push**：不得推送未签名 / 验签未通过的 commit；须先在本地修正签名环境再重新提交。该要求同样适用于 `docs`/`chore` 等非代码提交。
- 提交后可用 `git log --show-signature`（或平台 verified 状态）确认签名被平台认可。

#### 1.5.3 如实上报（异常时）
- **严禁自行生成 GPG 密钥**：新密钥公钥未登记到平台，会被判定为 `unknown_key`（verified 为 false），等同未签名。
- 若签名异常（`403 "Author is invalid"` / verified 为 false），优先核对 `user.name` / `user.email` 是否与 CNB 账号验证身份一致。
- 脚本执行失败时，**如实汇报**所见的报错行、`curl` 退出码、已执行步骤及结果，交由用户/人工判断。
- 若为变量未注入（脚本报 `未设置私钥解锁短语`）或分发 API 不可达，真实出路是修密钥仓库（如 `key/npc.yml`）的变量注入或排查网络链路，**禁止**在业务代码里打补丁掩盖。

## 2. 编码与代码规范 (Coding Standards)

### 2.1 语言与类型
- 核心代码库使用 **Python** 编写（本项目为 AstrBot 插件，要求 Python 3.12+）。
- 函数与关键变量必须提供**类型注解**，并通过 `pre-commit` 中的 `mypy`（`ignore-missing-imports`）检查。
- 禁止为图省事滥用 `Any`；能用具体类型或 `TypedDict` / `dataclass` 表达的地方必须明确类型。

### 2.2 命名与注释
- 变量和函数命名必须具备明确语义，遵循 PEP 8：函数/变量用 `snake_case`，类名用 `PascalCase`，常量用 `UPPER_SNAKE_CASE`。
- **必须提供中文注释**。特别是在以下场景：
  - 核心逻辑（如控制流、并发调度）。
  - 关键阈值与特殊补丁逻辑（如多 API Key 轮询、429 限流降级、防抖常量 `DEBOUNCE_SECONDS`）。
  - 正则表达式和复杂的 API 请求。

### 2.3 错误处理与日志
- 所有的异步调用（`async` / `await`）必须有妥善的 `try/except` 处理，避免异常逃逸导致任务中断。
- 使用项目内置的 `logger` 进行日志输出，禁止直接使用 `print()` 打印核心业务日志。
- 对于异常，必须在日志中保留完整的堆栈和上下文信息，便于后续诊断。

## 3. 工作流与文件操作行为准则 (Workflow Guidelines)

### 3.1 阅读先于修改（禁止盲猜代码）
- 在编辑任何文件之前，**必须先使用专用工具（如 `view_file`、`cat`、`grep` 等）读取文件的真实内容**。
- 严禁凭记忆或通用经验盲猜代码结构。

### 3.2 局部精准修改
- 在修改配置或代码（如调整防抖参数 `DEBOUNCE_SECONDS`、默认模型/尺寸）时，**必须进行局部精准的正则或行号匹配**。
- **绝对禁止全量覆盖**或意外替换无关内容，避免破坏其他已稳定的逻辑。

### 3.3 修改验证与闭环
- 修改代码后，必须通过 `git diff` 检查实际的变更内容是否符合预期。
- 确认没有混入无关修改后，方可进行 `git add` 和 `git commit` 操作。
- 每次完成任务后，必须确保所有修改已成功推送并提交 PR 到远程仓库的主分支（通过 PR 合并）。

### 3.4 主分支推送约束
- **除非用户明确要求直接推送到主分支**（如"推到主分支""直接合并到主分支""直接 push main"等），否则**禁止直接推送到主分支**。
- 所有代码变更一律通过创建 PR 将代码合并到主分支，确保变更可审查、可追溯。

### 3.5 Github 镜像仓库同步 PR（强制性提示词）
- **判定标准：只要 `.cnb.yml` 中存在将代码同步到 Github 的配置，即属于"同步到 Github 镜像仓库"的情况**（常见形式为在 `main: push` 事件下使用 `git-sync` 镜像同步 stage，或 `github-mirror` / `sync-github` / 镜像同步等类似 stage，目标指向 `github.com/...`）。**只要 `.cnb.yml` 里有这类配置，就必须在对应的 Github 镜像仓库创建一模一样的 PR**（同名、同分支、同变更内容）。
- 这是**强制性要求**，不得遗漏，确保 CNB 与 Github 镜像仓库的代码变更保持同步、可追踪。
- 创建 CNB PR 前，先检查本仓库 `.cnb.yml` 是否配置了到 Github 的同步/镜像能力（重点 grep `git-sync` / `github-mirror` / `sync-github` / `github.com` 等关键字）；若存在，则同步在 Github 镜像仓库创建完全一致的 PR。
- 若 `.cnb.yml` 中**没有任何**同步到 Github 的 stage（如仅有 `docker build & push`、知识库更新、代码扫描、NPC 触发等），则该仓库不适用本条双端同步要求，本 PR 只需在 CNB 维护即可。

## 4. 持续集成与部署规范 (CI/CD - .cnb.yml)

### 4.1 配置文件规范
- 本项目使用 CNB (Cloud Native Build) 构建流水线（基于 `.cnb.yml`）。
- 在修改 `.cnb.yml` 时，必须严格遵守 YAML 的缩进规范（通常为 2 个空格）。

### 4.2 环境依赖
- 如果在流水线的某一个 stage 中引入了需要构建或运行容器镜像的操作（如 `docker build`、`docker run`、基于其他镜像执行脚本等），**必须在该事件或作业级别明确声明 `services: - docker`**，否则会导致流水线无法正常挂载 Docker 守护进程。
- 参考示例：
```yaml
.npc: &npc
  - runner:
      cpus: 16
    services:
      - docker
    stages:
      - name: 启动NPC
```

## 5. 特定业务逻辑指导 (Domain Specifics)

### 5.1 上游 AI 接口调用（Gitee AI）
- **多 Key 轮询**：通过 `GiteeAIClient._get_next_api_key()` 按索引轮询多个 API Key；新增/调整 Key 解析逻辑时须保持 `parse_api_keys` 对「字符串」与「列表」两种配置的兼容。
- **限流与错误转换**：上游为 OpenAI 兼容接口，`429 Too Many Requests`、认证失败、`5xx` 等异常须在 API 层统一转换为中文 `RuntimeError`，由命令层捕获后回包友好提示，禁止把原始堆栈直接抛给用户。
- **防抖与并发**：请求统一走 `core/command_utils.check_rate_limit`（`DEBOUNCE_SECONDS=10`）与 `is_processing` 互斥，避免同一用户高频触发生图。

## 6. CNB OpenAPI 操作规范 (CNB OpenAPI Operations)

- **使用 curl 调用 API**：在执行任何与 CNB (Cloud Native Build) 相关的操作时，通过 shell 执行 curl 命令直接调用 CNB OpenAPI。
- **从 swagger.json 获取 API 信息**：调用接口前，先从 https://api.cnb.cool/swagger.json 获取最新 API 定义（含接口路径、请求方法、请求参数与鉴权要求），确保参数结构准确后再用 curl 执行。
- **强制查看帮助文档**：在调用 API 之前，请通过 OpenAPI 文档确认参数结构。

## 7. 运行时预装能力（按需使用）

- 本仓库 NPC 运行时镜像已**预装 Playwright 及 Google 浏览器内核（chromium）**，浏览器二进制位于 `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`，chromium 的系统依赖、CJK 中文字体（`fonts-noto-cjk`）与 fontconfig 均已装好，无头渲染中文页面不会出现"豆腐块"乱码。
- Agent 在**需要时**（浏览器自动化 / 网页抓取 / 前端页面截图等场景）可按需调用，无需额外安装或联网下载浏览器内核。
- **推荐：优先用现成的浏览器自动化便捷脚本** `/app/scripts/browser-automation.js`，无需手写样板代码：
  ```bash
  node /app/scripts/browser-automation.js title <url>                          # 页面标题（连通性自检）
  node /app/scripts/browser-automation.js text  <url> [--selector sel]         # 页面可见文本
  node /app/scripts/browser-automation.js html  <url> [--selector sel]         # 页面 HTML
  node /app/scripts/browser-automation.js shot  <url> /tmp/shot.png            # 整页截图
  node /app/scripts/browser-automation.js eval  <url> 'document.title'         # 页面内求值 JS 表达式
  ```
  脚本已内置 root 沙箱关闭参数、等待渲染缓冲与中文乱码规避等处理，详见脚本头注释。
- 若需在自研脚本中直接调用 Playwright API，请注意以下约定：
  - playwright 为**全局安装**，非项目依赖。任意路径的裸脚本里 `require('playwright')` 会因不在默认模块解析路径而失败，需先补全局搜索路径：
    ```js
    // 在 require('playwright') 之前执行
    if (!process.env.NODE_PATH) {
      const { execSync } = require('child_process');
      process.env.NODE_PATH = execSync('npm root -g', { encoding: 'utf8' }).trim();
      require('module')._initPaths(); // 让 NODE_PATH 立即生效
    }
    ```
    或在命令行加 `NODE_PATH="$(npm root -g)" node 你的脚本.js`。
  - 仅 Google 的 chromium 内核已预装并完成启动冒烟自检，以**无头（headless）**模式运行为主，运行时为 root，启动必须关闭沙箱与 /dev/shm，推荐统一传入（已在构建期冒烟自检验证）：
    ```js
    const { chromium } = require('playwright');
    const browser = await chromium.launch({
      chromiumSandbox: false,
      headless: true,
      args: ['--no-sandbox', '--disable-dev-shm-usage'],
    });
    ```
  - 请勿重复执行 `playwright install`，以免浪费下载与磁盘。

- **已预装 CodeQL CLI**（GitHub 官方静态代码安全扫描引擎，`/opt/codeql`），覆盖 JS/TS、Python、Java/Kotlin、C/C++、Go 等主流语言的语义级安全漏洞扫描。用法：
  ```bash
  # 构建 codeql 数据库并执行默认安全扫描（以 Python 为例）
  codeql database create /tmp/codeql-db --language=python --source-root=<项目路径>
  codeql database analyze /tmp/codeql-db python-code-scanning.qls --format=sarif-latest --output=results.sarif
  ```
  默认支持全部 codeql 标准查询包，无需额外下载。

## 9. 语音回复流程（TTS Voice Reply）

SuperNPC 支持把文字回复合成为**角色语音**再交付给用户：NPC 用 **Qwen3-TTS-12Hz-1.7B-Base** 声音克隆模型，以角色参考音频复现音色，把「文字回复」变成「文字 + 语音」的双通道回复。

- 能力入口：`tts-voice` 技能（`/root/.codebuddy/skills/tts-voice/`），核心脚本 `/root/.codebuddy/skills/tts-voice/scripts/npc_generate.py`。
- 音色素材：镜像预置于 `/root/.codebuddy/voices/`（`<角色名>.mp3` + `manifest.json`）。
- 模型路径：镜像预置 `/models/Qwen3-TTS-12Hz-1.7B-Base`，构建期固化，**无需联网下载**。

> **本章是「怎么用」的权威说明**：`9.1 使用引导`（它是什么 / 何时生效 / 我怎么管）→ `9.2 触发与时机`（该不该发语音）→ `9.3 参数与接口约定`（调什么、怎么调）。
> **现行口径（已收紧）：凡有音色素材，一律发声**——只要 `<角色名>.mp3` 存在，每次回复都默认必须附带语音，不因回复长短 / 类型而豁免。
> **⚠️ 但必须无条件的硬例外（安全红线）：命中「涉密 / 敏感内容」或「内容安全校验不通过」时，一律强制纯文字回复、严禁调用 TTS**——敏感信息不得被合成为持久化 / 可转发的音频附件。此类例外**不因「有素材」而豁免**（详见 9.2 三）。
> 其余降级情形（**素材不存在** / **合成或上传失败** / **合成环境不可用**）同样只发纯文字；任一情形都**绝不阻断主流程**。

---

### 9.1 语音回复使用引导（第一次接触请从这里开始）【必读】

> 本节回答三个问题：**它是什么 · 什么时候生效 · 我能怎么管**。

#### 一、一句话说清它是什么

**语音回复 = 把 NPC 的文字回复，用「角色音色」念出来的一个附加通道。**

- 用 **Qwen3-TTS 声音克隆**：给定一段 3~6 秒的角色参考音频（`ref_audio`）+ 与音频逐字对应的文本（`ref_text`），即可用该音色合成新语音。
- 交付形态是**一段 mp3 附件**（默认 `/workspace/voice.mp3`），随评论一起发出；用户看到的是「Markdown 文字 + 语音附件」。
- 它不是「把整篇正文念一遍」：语音文本是**展示文本的 60~120 字口语化摘要**，语音负责「让用户听到角色在回应」，正文负责「把信息讲清楚」。

由此推出两条核心设计：

- **展示文本与语音文本解耦**：Markdown 排版归展示文本；纯文本摘要归语音文本，两者是两份独立内容（见 9.3 三）。
- **语速/停顿交给模型**：不要手动切分文本，一次性传入摘要，模型会自行规划韵律（见 9.3 四）。

#### 二、触发链路：语音回复什么时候真的用上

```text
用户 @NPC 派发任务
      ↓
CNB 平台拉起 NPC 容器并注入环境变量（角色名、音色目录等）
      ↓
Agent 按 9.2 判定：先过安全门，再看素材门
      ↓
命中敏感 / 安全校验不通过 → 强制纯文字、严禁 TTS（不阻断主流程）
      ↓（未命中）
有素材 → 做存在性检查（<角色名>.mp3 是否存在）→ 提炼摘要 → 合成 → 上传附件 → 带链接回帖
无音色 / 合成上传失败 → 直接发 Markdown 文字回复（不阻断主流程）
```

- **无需手动开启**：只要镜像里预置了对应角色的 `<角色名>.mp3`，Agent 会在**每次回复时**自行调用 `tts-voice` 技能（有音色即发声），用户不必在指令里写「请发语音」。
- **安全例外自动生效**：命中「敏感内容 / 安全校验不通过」时，Agent **自动**改发纯文字、不调用 TTS（见 9.2 三 A 类），无需用户额外声明。
- **不由用户逐次指定音色**：音色由 **NPC 角色名**决定（脚本 `--name <角色名>`），不读取用户偏好。
- **无音色即静默降级**：官方语音库只覆盖部分英雄，**没有 `<角色名>.mp3` 的角色会跳过语音、只发文字**——这是预期行为，不是故障（见 9.2 三）。

#### 三、用户能做的三件事（人话版）

| 我想… | 怎么做 | 去哪里看结果 |
| --- | --- | --- |
| 知道当前角色有没有音色 | 让 NPC 检查音色目录，或直接看目录内是否有 `<角色名>.mp3` | 有则后续会发声；无则一直是纯文字 |
| 手动合成一条试听 | 在容器里跑 `"$TTS_PYTHON" /root/.codebuddy/skills/tts-voice/scripts/npc_generate.py --text "<60~120字摘要>" --name <角色名>` | 生成 `/workspace/voice.mp3` |
| 排查「为什么这次没语音」 | 看 9.2 三「不发语音的硬性禁区」+ 9.3 五「常见报错」 | 命中禁区（无素材 / 失败 / 敏感）属正常；否则按报错定位 |

> ⚠️ 合成耗时随字数近似线性增长：CPU 节点单条约 **40~60 秒**属正常。**严禁**拿整篇长回复去合成（核时浪费），语音文本务必摘要到 60~120 字。

#### 四、常见误解澄清（先看这几条，少走弯路）

| 误解 | 事实 |
| --- | --- |
| 「语音会把整篇正文念出来」 | **不会**。只念 60~120 字摘要，正文仍由 Markdown 承载 |
| 「每个角色都应该有语音」 | **不是**。官方语音库只覆盖部分英雄，无 `<角色名>.mp3` 就跳过，属预期 |
| 「没有语音说明功能坏了」 | **不是**。无音色 / 合成失败都会**降级为纯文字**，任务照样完成 |
| 「信息量大的回复可以不发语音」 | **不再成立**。口径已收紧为**有音色即发声**，长回复同样要附语音（正文照常排版，语音只取摘要） |
| 「有音色就必须发声，敏感内容也一样」 | **不是**。敏感内容 / 安全校验失败是**压倒性的硬例外**，即使有素材也**必须**纯文字、严禁 TTS（见 9.2 三 A 类） |
| 「合成了但没附链接也算完成」 | **不是**。交付必须上传附件并附 `asset_link`，否则用户听不到（见 9.3 五） |
| 「要手动分段才自然」 | **不用**。一次传完整摘要，模型自行规划停顿，手动切分反而更生硬 |

#### 五、概念速查表（后文高频术语）

| 术语 | 含义 | 对应参数 / 变量 |
| --- | --- | --- |
| 参考音频 | 复现音色所用的 3~6 秒素材样本 | `<角色名>.mp3` / `ref_audio` |
| 参考文本 | 与参考音频**逐字对应**的文本（写错会毁掉音色） | `manifest.json.ref_text` |
| 音色目录 | 存放 `<角色名>.mp3` 与 `manifest.json` 的目录 | `--voices-dir` / `VOICES_DIR` |
| 展示文本 | 发给用户看的 Markdown 正文 | —— |
| 语音文本 | 传给 `--text` 的纯文本摘要（60~120 字） | `--text` |
| 语音解释器 | 装了 `torch` + `qwen_tts` 的独立 venv | `$TTS_PYTHON`（`/opt/tts-venv/bin/python`） |
| 模型目录 | Qwen3-TTS 权重所在目录（构建期固化） | `--model-path` / `TTS_MODEL_PATH` |

---

### 9.2 触发与时机（有音色即发声）【强制必读】

> 本节回答「**Agent 什么时候该发语音**」。没有这一节，后面的参数只是「怎么调」，Agent 不知道「该不该调」。

**总原则（已收紧）：有音色就发声，不挑场景——只要 `<角色名>.mp3` 存在，每次回复都默认必须附带语音。豁免仅两类：①【安全硬例外·最高优先级】命中「涉密/敏感内容」或「内容安全校验不通过」→ **强制纯文字、严禁 TTS**，与有无素材无关；②【能力降级】素材不存在 / 合成环境不可用 / 合成或上传失败 → 降级纯文字。任一情况均不阻断主流程。**

> 📌 **口径变更记录**：早期口径为「语音是增强能力，仅在命中触发场景时才发声」（即允许「纯信息型长回复」走纯文字）。应触发者要求，现行规则已**收紧为「凡有音色一律发声」**；下方「二、典型发声场景」列的是**典型场景（非穷举）**，「三、不发语音的硬性禁区」保留**安全硬例外**（敏感内容 / 安全校验失败）与**能力降级**（无素材 / 环境不可用 / 合成上传失败）两类，不再以「信息密度高」为由豁免发声。
> 🔒 **收紧的边界**：本次收紧**只放宽「因内容形态而不发声」，绝不放宽「因内容安全而不发声」**——敏感内容与安全校验失败始终是**压倒一切的硬例外**，优先级高于「有音色即发声」。

#### 一、先做存在性检查（调用前必做）

先按 9.3 二 的目录查找顺序定位音色目录，确认其中存在 `<角色名>.mp3`：

```bash
# 镜像预置目录（NPC 被召唤到任意仓库时的实际命中项）
ls "/root/.codebuddy/voices/<角色名>.mp3"
```

- **存在** → 继续合成流程。
- **不存在** → **跳过语音**，直接撰写 Markdown 文字回复并发送评论即可（属预期，非故障）。

#### 二、典型发声场景（列举，非穷举）

> **口径已收紧：有音色就一律发声**，下表只是「最该发声」的典型场景，**不是**发声的必要条件。凡素材存在、且**未命中 9.2 三 A 类安全硬例外**，下表**未列出**的回复同样要发声。

| 典型场景 | 说明 |
| --- | --- |
| 常规任务回复 / 结果汇报 | 用户在等答案，语音让「角色在回应」的体感更强 |
| 战斗 / 施法 / 强化等**带情绪的业务场景** | 情绪张力是语音的价值所在 |
| 短小、口语化的答复 | 60~120 字内能讲清结论的答复最适合发声 |
| 用户明确要求「说/念/语音」 | 用户显式诉求，优先级最高 |
| **纯信息型长回复（表格 / 代码 / 多段说明）** | **也要发声**：正文照常 Markdown 排版，语音只取 60~120 字摘要（见 9.3 三），信息密度高**不再**构成豁免理由 |

#### 三、不发语音的**硬性禁区**（收紧后仅存这两类，安全优先）

> 除下列硬性禁区外，**只要素材存在就要发声**——「内容信息密度高」**不再是**不发语音的理由。
> 两类禁区**优先级不同**：**A 类（安全红线）压倒一切**，即使素材存在也**必须**纯文字；**B 类（能力降级）**是「发不出来」时的兜底。二者都**不阻断主流程**。

**A 类 · 安全硬例外（最高优先级，与有无素材无关，必须纯文字、严禁 TTS）**

- **涉密或敏感内容**：Token、密钥、私钥、密码、隐私信息、内部链接等**严禁**进入语音。语音附件会被**持久化并可被转发**，敏感信息一旦合成即等同泄露与扩散；此类内容**只发纯文字**（如仍不宜展示，则脱敏或以「涉及敏感信息，已省略」代替）。
- **内容安全校验不通过**：违法违规、色情低俗、暴力恐怖、歧视仇恨、虚假冒充（公检法/政府话术）、隐私侵犯——**拒绝合成**，只发纯文字并说明原因。
- **判据**：只要本次回复的**展示文本或其摘要**中任一片段落入上述范围，即**判定命中** → 直接走纯文字，**不得**因为「有音色素材」而豁免。**摘要同样受检**：不允许「正文脱敏、摘要仍泄漏」。

**B 类 · 能力降级（发不出来时的兜底，非主动禁声）**

- **无音色素材**（`<角色名>.mp3` 不存在）：直接发文字，**不要**报错、不要重试。
- **合成环境不可用**（模型路径 / 解释器缺失）或**合成 / 上传失败**：**降级为纯文字**（一句话说明即可），**不得**因此中断任务或反复重试。

#### 四、标准动作顺序（一句话流程）

```text
写回复 → ① 安全门（最高优先级）：命中「敏感内容 / 安全校验不通过」？
          → 是 → 强制纯文字回复，严禁调用 TTS（结束）
          → 否 → ② 素材门：有音色素材？
                   → 有 → 提炼 60~120 字摘要（摘要同样过安全门）→ 合成 → 上传附件 → 带链接回帖
                   → 无 → 直接发 Markdown 文字回复
任一环节失败 / 环境不可用 → 降级为纯文字（告警即可，绝不阻断主流程）
```

> **顺序纪律**：**安全门永远先于素材门**。任何时候都**不允许**以「有音色素材」为由，绕过安全门把敏感内容送进 TTS。

---

### 9.3 参数与接口约定（以脚本 `--help` 为准，勿凭记忆臆测）

> 本节是「调什么、怎么调、怎么排错」的落地说明，与 `tts-voice` 技能脚本 `/root/.codebuddy/skills/tts-voice/scripts/npc_generate.py` **逐项对齐**。

#### 一、运行环境（SuperNPC 镜像）

| 项 | 值 | 说明 |
| --- | --- | --- |
| 解释器 | `$TTS_PYTHON` = `/opt/tts-venv/bin/python` | 独立 venv，含 `torch(cpu)` + `qwen-tts`；**禁用裸 `python3`**（镜像是 Anaconda 的，未装 `qwen_tts`） |
| 模型 | `/models/Qwen3-TTS-12Hz-1.7B-Base` | 构建期固化，无需联网下载 |
| 音色素材 | `/root/.codebuddy/voices/` | `<角色名>.mp3` + `manifest.json` |
| 设备 | 自动探测 | 有 GPU 用 GPU，否则自动降级 CPU，**无需配置** |

#### 二、目录查找顺序（音色 / 模型）

脚本需在**任意仓库**的工作区里找到音色与模型，故按固定顺序探测，取第一个命中项：

**音色目录**（取「同时存在 `<角色名>.mp3` 与 `manifest.json`」的第一个）：

1. 环境变量 `VOICES_DIR`（显式覆盖，最高优先级）
2. 仓库根 `voices/`
3. 当前工作目录 `voices/`
4. **`~/.codebuddy/voices`（镜像内 `/root/.codebuddy/voices`，NPC 运行时的实际命中项）**

**模型目录**（取第一个真实存在的目录）：

1. 环境变量 `TTS_MODEL_PATH`（镜像已注入，最高优先级）
2. 命令行 `--model-path`
3. **`/models/Qwen3-TTS-12Hz-1.7B-Base`（镜像预置，NPC 运行时的实际命中项）**
4. 仓库根 `models/Qwen3-TTS-12Hz-1.7B-Base`
5. `/workspace/models/Qwen3-TTS-12Hz-1.7B-Base`（兜底）

> ⚠️ 踩坑：若一路都没命中，`from_pretrained` **不会联网下载**，而是把不存在的本地路径当 HF repo id 解析，抛 `HFValidationError: Repo id must be in the form 'repo_name' or 'namespace/repo_name'`。看到该报错 = 模型路径没命中，显式传 `--model-path` 或注入 `TTS_MODEL_PATH` 即可。

> ⚠️ 形态约定：音色素材**不要**放 `/workspace/voices`——NPC 运行时 workdir 常为 `/workspace`（**调用方仓库的工作区**），会被调用方代码覆盖而丢失。镜像里只预置一份到 `/root/.codebuddy/voices`。

#### 三、展示文本 vs 语音文本（解耦）

展示文本（Markdown 正文）与语音文本（`--text` 纯文本）是**两份独立内容**：

- **展示文本**：允许多段、列表、加粗、表格等 Markdown 排版。
- **语音文本**：**展示文本的 60~120 字口语化摘要**（不是全文副本），剥离 Markdown 标记后**一次性**传入。

剥离规则（在「已摘要」的基础上应用）：

| 要去掉的内容 | 处理方式 |
| --- | --- |
| Markdown 标题（`#`、`##`） | 删除 `#`，保留标题文字 |
| 列表符号（`- `、`* `、数字序号） | 删除符号，保留文字 |
| 加粗 / 斜体（`**`、`*`、`__`） | 删除标记，保留文字 |
| 代码块 / 行内代码（`` ` ``） | 删除标记，保留内容 |
| 图片（`![...](...)`） | 整体删除 |
| 链接（`[文字](url)`） | 保留文字，删除括号与 URL |
| 感叹号（`！` / `!`） | 替换为句号（模型对感叹号支持不好） |
| 招呼语（「你好」「@用户名」） | 删除 |
| `[laughing]` 标签 | 禁止使用（模型支持不稳定，脚本会自动过滤） |

> **摘要化是硬约束**：TTS 推理耗时随字数近似线性增长，脚本默认上限 120 字，超长会自动按句末标点裁剪并告警——这是**兜底**，正常流程应在生成语音文本时就控制到 60~120 字。

#### 四、脚本参数速查（复用脚本，勿手写样板）

```bash
# 推荐：在仓库根执行，用 TTS_PYTHON 调用，传入 60~120 字口语化摘要
cd /workspace && "${TTS_PYTHON:-/opt/tts-venv/bin/python}" /root/.codebuddy/skills/tts-voice/scripts/npc_generate.py \
  --text "这是一段六十到一百二十字的口语化摘要。" --name 妲己
```

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--text` | 是 | 语音文本；支持多段（`nargs="+"`），多段会自动 join 成一整段，**不要**手动切分 |
| `--name` | 是 | NPC 角色名；按此名在音色目录取 `<name>.mp3` 与 `manifest.json` 加载音色 |
| `--output` | 否 | 输出路径，默认 `/workspace/voice.mp3`；**后缀决定格式**（`.mp3` 需 ffmpeg / `.wav` 无损） |
| `--voices-dir` | 否 | 显式指定音色目录；默认按 9.3 二 顺序自动定位 |
| `--model-path` | 否 | 显式指定模型目录；不传则按 9.3 二 顺序自动定位 |
| `--mp3-bitrate` | 否 | mp3 比特率，默认 `64k`（可 `96k` / `128k`） |
| `--max-chars` | 否 | 语音文本长度上限，默认 `120`（也可用环境变量 `TTS_MAX_CHARS`） |
| `--log-level` | 否 | 日志级别 `debug`/`info`(默认)/`warn`/`error`（也可用 `TTS_LOG_LEVEL`） |
| `--log-file` | 否 | 把 DEBUG 全量日志同时落盘（也可用 `TTS_LOG_FILE`） |

输出：默认 `/workspace/voice.mp3`（libmp3lame 64k CBR mono，10 秒约 80KB，是同长 wav 的约 1/6）。

#### 五、交付与排障

**交付（必做，不可省略）**：合成后用 CNB 技能 `upload-attachment` 上传 `/workspace/voice.mp3`，回复中**必须**附上附件链接（`asset_link`）。**禁止套话**：不要在展示文本末尾加「让我用声音说给你听」之类的话。

**结构化日志**：脚本每条日志前缀为**相对启动秒数**（如 `[+00012.34s]`），末尾打印各阶段耗时占比 `PROFILE 摘要`，可直接定位慢在哪一步。常用组合：

```bash
"${TTS_PYTHON:-/opt/tts-venv/bin/python}" /root/.codebuddy/skills/tts-voice/scripts/npc_generate.py \
  --text "摘要文本" --name 妲己 --log-level debug --log-file /tmp/tts.log
```

| 现象 / 日志 | 含义与处置 |
| --- | --- |
| `RTF` > 1 | 推理比实时还慢（CPU 节点常见），属正常 |
| `参考音频几乎无声` | 该角色 `.mp3` 素材有问题，克隆音色会失效 |
| `文本超过 200 字` | 超出模型单次稳定合成长度，应精简文本 |
| `语音文本已按上限裁剪` | 调用侧漏了摘要化，应在生成时就控制到 60~120 字 |
| `HFValidationError: Repo id must be ...` | 模型路径没命中，显式 `--model-path` / `TTS_MODEL_PATH` |
| `ModuleNotFoundError: qwen_tts` | 用了裸 `python3`，改用 `$TTS_PYTHON` |
| 合成失败 | 打完整堆栈 + 已完成阶段耗时；**降级为纯文字回复**，不阻断任务 |

> **排错纪律**：日志中只保留非敏感字段（角色名、路径、耗时）；**严禁**把密钥、Token 等敏感信息贴进评论或日志。

#### 六、使用纪律（强制）

- **摘要优先**：语音文本固定 60~120 字，**严禁**把整篇长回复丢进 `--text`（核时浪费的主因）。
- **失败降级**：无音色 / 合成失败 / 环境缺失，一律**降级为纯文字回复**，**不得**中断 NPC 主流程。
- **交付闭环**：合成成功必须上传附件并附 `asset_link`，否则视为未完成。
- **素材不落调用方**：音色放镜像预置目录（`/root/.codebuddy/voices`），**不要**写进 `/workspace/voices`，避免被调用方工作区覆盖。
- **逐字对应**：`manifest.json.ref_text` 必须与参考音频逐字对应，写错会直接毁掉克隆音色。
- **文档与脚本同源**：本节参数表 / 示例 / 报错文案均须与 `/root/.codebuddy/skills/tts-voice/scripts/npc_generate.py` 保持一致；改脚本时同步改文档（以 `--help` 为准）。

---

## 10. 阿里云百炼记忆库（长期记忆）(Bailian Memory)

SuperNPC 通过 **`/app/scripts/bailian-memory.py`** 接入**阿里云百炼记忆库 API**，为 NPC / Agent 提供跨会话的长期记忆能力：把对话或结论写入记忆库，后续会话再按语义检索召回，避免「每次任务都从零开始」。

- 官方文档：<https://docs.agent.bailian.aliyun.com/zh/api/memory/fragments/add-memory>（同组还有「搜索 / 列出 / 更新 / 删除记忆」与「用户画像」接口）。

> **📌 运行时 vs 仓库的边界（先读这条，避免照抄路径撞空）**：本脚本是 **SuperNPC 运行时能力**，真身固化在**运行时镜像的 `/app/scripts/bailian-memory.py`**，与物理上由哪个仓库（如本仓库 `astrbot_plugin_models_ai`，一个 AstrBot 生图插件）拉起 NPC **毫无血缘**。因此：
> 1. 本章所有命令示例一律使用**运行时绝对路径 `/app/scripts/bailian-memory.py`**，可直接复制执行，**不依赖当前工作目录**；
> 2. **不要**把该脚本复制进被拉起仓库（会污染其项目边界），也**不要**假定被拉起仓库内存在 `scripts/bailian-memory.py`；
> 3. 要改脚本本体，应去 **SuperNPC 仓库**改；被拉起仓库要动的只是**文档口径**（同类教训见 1.5 节：早期 `scripts/gpg-setup.sh` 等文件本仓库并不存在的注记）；
> 4. 同理，本章涉及的脚本回归 / 自检用例（如接口契约回归、使用引导自检）**只在 SuperNPC 仓库存在**，被拉起仓库不必、也无法执行。

### 10.1 记忆库使用引导（第一次接触请从这里开始）【必读】

> 本节是**入口**，面向「刚知道有记忆库、想用起来」的读者，回答三个问题：**它是什么 · 何时生效 · 我能怎么管**。
> 读完后按顺序往下看：`10.2 使用时机`（该不该调）→ `10.3 接口约定`（调什么）→ `10.6 快速开始`（怎么跑通）。

#### 一、一句话说清它是什么

**记忆库 = 一个按「人」归口、本组织所有仓库共用的语义知识池。**

- Agent 每完成一次任务，可以把「跨仓库可复用的结论」写进去（`add`）；
- 下次在**任意仓库**接到相关任务，可以先按语义检索召回（`search`），复用历史结论，**不必重新踩坑、不必重复问用户**。
- 它不是聊天记录、不是日志仓库、也不是代码仓库——**只存结论性知识**（平台约定 / 排查经验 / 用户长期偏好 / 业务规则）。

由此推出两条与「用哪个仓库」无关的设计（细节见 10.5）：

- **库只有一份**：所有仓库共用同一个 `memory_library_id`，无需每个仓库单独配置；
- **人只有一个键**：`user_id` 就是**触发者登录名**本身（如 `qixiaoxin`），不拼组织、不拼仓库 → 同一个人在本组织所有仓库写入的记忆，**用同一个 user-id 就能全部检索到**。

#### 二、触发链路：记忆库什么时候真的被用上

```text
用户在 Issue / PR 评论里 @NPC 派发任务
        ↓
CNB 平台拉起 NPC 容器（npc:go）并注入环境变量
        ↓
NPC 读取 AGENTS.md 第 10 章（本章）决定「要不要用记忆库」
        ↓
命中 10.2 的触发场景 → 任务开始先 search；产出可复用结论 → 任务收尾 add
        ↓
调用 /app/scripts/bailian-memory.py（唯一入口）写入 / 检索同一个记忆库
```

- **无需手动开启**：只要密钥仓库注入了 `DASHSCOPE_API_KEY`，NPC 在需要时**自行判断**是否读写；未注入时脚本会**快速失败并跳过**记忆环节，任务照常完成（不阻断主流程）。
- **不由用户逐次指定**：是否 search / add 由 Agent 依据 10.2 的场景表自行决定，用户无法也不需要在指令里写「请使用记忆库」。
- **用户可以使用的四个开关**（都可选，按优先级从高到低）：

  | 想做的事 | 做法 | 生效范围 |
  | --- | --- | --- |
  | 强制统一到某个实体 | 密钥仓库注入 `MEMORY_USER_ID`（如 `qixiaoxin`） | 该密钥仓库覆盖的所有仓库 |
  | 临时指定某次调用的实体 | 调脚本时显式传 `--user-id` | 仅本次调用 |
  | 切到另一个记忆库 | `MEMORY_LIBRARY_ID` 或 `--memory-library-id` | 注入范围 / 本次调用 |
  | 关闭仓库溯源元数据 | `MEMORY_AUTO_META_DATA=0` | 注入范围 |

- **模型不属于记忆库**：记忆库调用与「NPC 用哪个大模型」是两件事。模型由 `.cnb.yml` 的 NPC 配置与密钥仓库变量（如 `PLUGIN_AI_MODEL`）决定，**不是**记忆库的配置项——排查记忆问题时不要往模型上找原因。

#### 三、一条记忆的完整生命周期

```text
① 产生  任务收尾，Agent 判断「这条结论跨仓库可复用」→ add（≤ 512 字符，讲清「结论 + 适用场景」）
② 召回  后续任一仓库的 Agent 任务开始时 search（语义匹配，相似度阈值默认 0.6）→ 命中即作为先验复用
③ 纠偏  结论过时/不准确 → 先 search 拿到 memory_node_id，再 update 改写（不要重复 add）
④ 退役  结论彻底失效 → delete（不可恢复，删前必须用 search / list 确认 node_id 正确）
```

- 第 ① 步是**唯一入口**：内容质量决定后续召回质量，所以「写成一句可复用的结论」比「写得多」更重要。
- 第 ③ 步是**纪律**：同一结论重复 `add` 会产生多个近似片段，**污染召回结果**（召回时互相挤占名额），必须用 `update`。

#### 四、用户能做的四件事（人话版）

| 我想… | 怎么做 | 去哪里看结果 |
| --- | --- | --- |
| 知道记忆库到底存了什么 | 让 NPC「列出我的记忆」（它会用同一 user-id 调 `list`） | NPC 评论里的 `[memory] 本页 N 条记忆` + 逐条内容 |
| 手动写入一条结论 | 让 NPC「记住：<结论>」，或在**运行时容器内**跑 `/app/scripts/bailian-memory.py add --content "…"`（脚本只活在运行时镜像，本地 / 被拉起仓库内均无此物） | `[memory] 写入成功，变更片段 1 条` |
| 验证某条结论是否已入库 | 让 NPC「检索记忆：<关键词>」 | `[memory] 命中 N 条记忆`（命中 0 条属正常，说明还没沉淀过） |

> ⚠️ 手动 `delete` 前务必先检索确认 `memory_node_id`：**删除不可恢复**，误删只能重新写入。

#### 五、常见误解澄清（先看这几条，少走弯路）

| 误解 | 事实 |
| --- | --- |
| 「每个仓库要单独配一套记忆库」 | **不用**。库与实体都跨仓库共享（见 10.5），零配置即可跨仓库召回 |
| 「记忆是按仓库隔离的，A 仓库看不到 B 仓库」 | **不是**。`user_id` 与仓库无关，A 仓库写入的结论在 B 仓库可直接召回；仓库信息只作 `meta_data` 溯源 |
| 「要把整段对话原样丢进去才记得住」 | **不需要**，只写提炼后的结论；整段对话灌入会稀释检索质量，`--content` 上限 512 字符 |
| 「记忆库坏了任务就该失败」 | **不会**。记忆是增强能力，调用失败只告警、继续完成任务（见 10.10 使用纪律） |
| 「没注入 Key 就是坏了」 | **不是**。未注入 `DASHSCOPE_API_KEY` 时脚本按设计**快速失败并跳过**，属预期行为（见 10.8 常见报错与排错） |

#### 六、概念速查表（后文高频术语）

| 术语 | 含义 | 对应参数 / 变量 |
| --- | --- | --- |
| 记忆库 | 记忆的隔离边界，本组织所有仓库共用一份 | `memory_library_id` / `MEMORY_LIBRARY_ID` |
| 记忆实体 | 记忆的归属人（**本组织内一个人一个键**） | `user_id` / `MEMORY_USER_ID` |
| 记忆片段 | 一条被存下来的结论（可增删改查） | 响应里的 `memory_nodes[]` |
| 记忆节点 ID | 单条片段的唯一标识，`update` / `delete` 必须用它 | `memory_node_id` / `--node-id` |
| 画像模板 | 可选能力，指定后额外提取用户画像（不传则只存片段） | `profile_schema` / `MEMORY_PROFILE_SCHEMA` |
| 溯源元数据 | 自动附加的来源仓库等信息，**不参与主键** | `meta_data`（`repo_slug` 等） |

### 10.2 使用时机（何时读、何时写、何时不用）【强制必读】

> 本节回答「**Agent 什么时候该用这个记忆库**」。没有这一节，后面 10.6~10.9 只是「怎么调、怎么排错」，Agent 不知道「该不该调」。

**总原则：记忆库是「增强能力」而非「必经环节」——只在「本次任务能从中获益 / 能留下可复用结论」时读写，其余情况一律不用。**

#### 一、开始任务前：先 `search` 召回（读）

**满足以下任一条件时，应先在任务开始阶段 `search` 一次**（`--query` 用任务关键词或用户原话）：

| 触发场景 | 说明 | 示例 query |
| --- | --- | --- |
| 任务涉及**本组织平台约定 / 规范** | 流水线模板、密钥仓库注入、GPG 签名链路、目录结构等组织级约定 | `镜像构建复用模板怎么用` |
| 疑似**踩过的坑 / 历史排查经验** | 报错、构建失败、鉴权 403、网络偶发 EOF 等 | `GPG 签名 unknown_key 怎么办` |
| 用户提到**「上次 / 之前 / 老规矩 / 照旧」** | 用户显式指向历史结论 | `上次说这个字段怎么处理` |
| 用户提出**个人偏好 / 长期约定** | 编码风格、工具选型、提醒事项等 | `我的编码风格偏好` |
| **长任务 / 多轮任务**的后续轮次 | 上一轮结论已入库，本轮需接着干 | `这个 PR 之前的结论` |

- 召回命中（`similarity_threshold` 建议 0.5~0.7）后，**优先复用历史结论**，避免重复踩坑 / 重复问用户。
- 召回为空属**正常结果**，不必重试、不必报错，按常规流程继续即可（长期记忆本就该「没有就返回空」）。

#### 二、任务结束时：再 `add` 沉淀（写）

**仅当产出「跨仓库可复用」的结论性知识时，才在任务收尾 `add` 写入**，典型是这四类：

| 可写入（推荐） | 反例（禁止写入） |
| --- | --- |
| 组织级**平台约定 / 规范**（如 `docker.yml` 复用模板） | 逐次任务流水、命令执行日志 |
| **排查经验 / 踩坑结论**（含错误码与解法） | 本次 PR 的临时上下文、一次性 diff |
| 用户**明确表达的长期偏好** | 未脱敏的 Token / 密钥 / 隐私 / 内部链接 |
| 可复用的**业务规则 / 字段口径** | 只在单个仓库成立的临时信息（应放 `meta_data`） |

- 一次只写**一条结论**（`--content` 控制在 512 字符内，讲清「结论 + 适用场景」），不要把整段对话原样灌入。
- 同一结论若**已存在**（`search` 已召回）→ 用 `update` 补充，**不要**重复 `add` 制造重复片段。
- 结论**已失效 / 被推翻** → 用 `update` 修正或 `delete` 删除，别留着污染后续召回（`delete` 不可恢复，先确认 `memory_node_id`）。
- 用户未授权时不要擅自把用户隐私偏好入库；不确定某条是否「可公开复用」，**宁可不写**。

#### 三、什么情况**不要用**记忆库

- **纯一次性任务**：单次问答、改个错别字、看一眼状态——读写都是噪音。
- **答案只依赖本次上下文 / 代码本身**：直接读代码 / 看日志更快，不要绕道记忆库。
- **鉴权缺失**（`DASHSCOPE_API_KEY` 未注入）：**跳过**记忆环节，按 10.10「失败不阻断主流程」继续完成任务，**不要**反复重试或中断任务。
- **涉及敏感信息**：脱敏后仍无法安全复用的，直接不写。
- **仓库特有的临时信息**：不该进共享记忆线（会污染其它仓库检索），需要时放 `meta_data`。

#### 四、标准动作顺序（一句话流程）

```text
任务开始 → 判断「是否需要历史结论？」→ 是 → search 召回 → 复用/纠偏
任务收尾 → 判断「是否产出可复用结论？」→ 是 → 已存在则 update，否则 add
任一记忆调用失败 → 告警 + 继续任务（绝不阻断主流程）
```

> 若本次任务**既不 search 也不 add**，属正常情况（大多数一次性任务如此），无需在评论里解释原因。

### 10.3 接口约定（以官方文档为准，勿凭记忆臆测）

- **服务地址**：`https://dashscope.aliyuncs.com/api/v2/apps/memory`
- **鉴权**：请求头 `Authorization: Bearer $DASHSCOPE_API_KEY`。该 Key 为**账号级凭证**，**严禁**写入代码仓库 / 日志 / 评论，只能通过密钥仓库导入环境变量。
- **协议**：仅 HTTPS；请求体与响应体均为 JSON（UTF-8）。
- **方法约定**：写入 / 检索用 `POST`，列表查询用 `GET`，更新用 `PATCH`，删除用 `DELETE`。
- **记忆片段接口一览**：

  | 能力 | 方法 | 路径 |
  | --- | --- | --- |
  | 添加记忆 | POST | `/add` |
  | 搜索记忆 | POST | `/memory_nodes/search` |
  | 列出记忆 | GET | `/memory_nodes` |
  | 更新记忆 | PATCH | `/memory_nodes/{memory_node_id}` |
  | 删除记忆 | DELETE | `/memory_nodes/{memory_node_id}` |

- **添加记忆关键参数**：`user_id`（记忆实体 ID，最大 64 字符；**省略时自动推导为触发者登录名，如 `qixiaoxin`**，见 10.5）；`messages`（数组，最多 50 条，每项含 `role`=user/assistant 与 `content`）与 `custom_content`（字符串，最大 512 字符）**二者互斥**，填 `custom_content` 后会**忽略** `messages`；`profile_schema` 不传则**仅写记忆片段、不提取用户画像**；`memory_library_id` **已默认写死为 `22fcd3f37eee42d6ac99cf25d03ac6c3`**（见下），`project_id` 不传则使用默认规则。
- **搜索记忆关键参数**：`query`（必填）、`max_results`（1~100）、`rewrite` / `rerank`（默认建议开启）、`similarity_threshold`（0.0~1.0，建议 0.5~0.7）、`plan_version`（`Pro` / `Lite`，默认 Pro）。
- **响应字段**：成功响应统一含 `request_id` 与 `memory_nodes[]`；`memory_nodes[].event` 为操作类型 `ADD / UPDATE / DELETE`，`old_content` 仅在 `event` 为 `UPDATE` 时有效。
- **错误码与重试**：`4xx`（限流除外）为参数 / 鉴权问题，**快速失败不重试**；`429 限流`与 `5xx` 采用 **1s / 2s / 4s 指数退避，最多 3 次**；错误响应结构为 `{code, message, request_id}`，排错务必带上 `request_id`。

### 10.4 环境变量（全部经密钥仓库注入，禁止硬编码）

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `DASHSCOPE_API_KEY` | 是 | 百炼 API Key；缺失时脚本直接报错退出（**不裸调**） |
| `MEMORY_USER_ID` | 否 | 记忆实体 ID；显式注入时**优先级最高**，可强制统一到指定实体 |
| `MEMORY_AUTO_META_DATA` | 否 | 是否自动注入仓库溯源元数据（默认 `1`；置 `0` 关闭） |
| `CNB_BUILD_USER` / `CNB_COMMITTER` | 否 | 触发用户（登录名），**默认 `user_id` 即取其值**（如 `qixiaoxin`），不带组织/仓库前缀 |
| `CNB_BUILD_USER_EMAIL` / `CNB_COMMITTER_EMAIL` | 否 | 触发用户邮箱；无登录名时取其 local-part 兜底（同一人多来源归一化到同一实体） |
| `CNB_ROOT_SLUG` / `CNB_GROUP_SLUG` | 否 | 根组织 slug，**仅**用于无人上下文（定时任务）回落组织级实体与元数据，**不参与** `user_id` 主键 |
| `MEMORY_LIBRARY_ID` | 否 | 记忆库 ID，**默认已写死为 `22fcd3f37eee42d6ac99cf25d03ac6c3`**，显式注入可覆盖 |
| `MEMORY_PROJECT_ID` | 否 | 记忆片段规则 ID，不传使用默认规则 |
| `MEMORY_PROFILE_SCHEMA` | 否 | 画像模板 ID，不传则不提取用户画像 |
| `MEMORY_API_BASE_URL` | 否 | 覆盖服务地址（仅测试 / 私有网关场景使用） |
| `MEMORY_REQUEST_TIMEOUT` | 否 | 单次请求超时秒数（默认 30） |
| `MEMORY_MAX_RETRIES` | 否 | 429 / 5xx 最大重试次数（默认 3） |

### 10.5 记忆共享策略（本组织所有仓库、同一个人共用一条记忆线）【强制】

**核心诉求**：**同一个人**在本组织下的**所有仓库**，长期记忆写入**同一个记忆库、同一个记忆实体**，实现「A 仓库踩过的坑，B 仓库能直接召回」，且检索时**只需记住自己的登录名**。

- **库（`memory_library_id`）是隔离边界**，已写死为 `22fcd3f37eee42d6ac99cf25d03ac6c3`，所有仓库共用。
- **实体（`user_id`）统一为触发者登录名本身**（如 `qixiaoxin`），**不内嵌组织、不内嵌仓库**，默认按下列优先级推导（见脚本 `default_user_id()`）：

  | 优先级 | 取值来源 | 结果示例 | 说明 |
  | --- | --- | --- | --- |
  | 1 | `--user-id` 显式传参 | `team_shared` | 最高优先级 |
  | 2 | `MEMORY_USER_ID` 环境变量 | `qixiaoxin` | 密钥仓库可强制统一 |
  | 3 | **触发者登录名（默认）** | `qixiaoxin` | **推荐**：与组织 / 仓库上下文**完全无关**，同一人在所有仓库、所有根组织解析结果完全一致 |
  | 4 | `usr_<根组织>` | `usr_XMZZUZHI` | **仅**无人上下文（如定时任务）时回落，避免无人任务污染某个人的记忆线 |

  第 3 级的登录名取值链（同一人在不同仓库可能只注入其中某一个，故需多级互为回退）：

  | 子优先级 | 取值来源 | 说明 |
  | --- | --- | --- |
  | 3.1 | `CNB_BUILD_USER` | 登录名，最稳定 |
  | 3.2 | `CNB_COMMITTER` | 可能是昵称/全名，统一小写归一化后仍可用 |
  | 3.3 | `CNB_BUILD_USER_EMAIL` → `CNB_COMMITTER_EMAIL` 的 local-part | 兜底；邮箱取 `@` 前、并剥离 `+` 别名 |

- **本条是强制纪律**：
  1. **禁止**把 `repo_slug`（仓库路径）当作 `user_id`——按仓库切分会让记忆碎片化，同组织其它仓库检索不到，违背长期记忆初衷；
  2. **禁止**把组织上下文（`CNB_ROOT_SLUG` / `CNB_GROUP_SLUG`）拼进 `user_id`——**同一人就该是同一个键**（如 `qixiaoxin`），拼组织会让同一人在不同根组织被拆成多个实体，检索时必须先知道组织名，违背「一个 user-id 贯穿」的诉求；
  3. **同一人必须命中同一 `user_id`**：不要依赖「本次运行恰好注入了哪些用户变量」——脚本已对登录名/昵称/邮箱做归一化，保证同一个人在**所有仓库、所有组织**解析出同一个登录名；
  4. 确需租户级隔离时，**换记忆库**（`memory_library_id`）而**不是**改 `user_id`；
  5. 仓库维度只作为**元数据**保留：`add` 时脚本自动把 `repo_slug` / `repo_scope` / `user_identity` 合并进 `meta_data`（可用 `--meta-data` 覆盖，或用 `MEMORY_AUTO_META_DATA=0` 关闭），既能跨仓库召回，又能追溯记忆来源与归属人；
  6. 只有确实需要「项目独立记忆」时才显式传 `--user-id`，并需在 PR 中说明原因。

- **跨仓库召回示例**：在 `XMZZUZHI/SuperNPC` 写入的结论，可在本组织其它仓库（乃至其它组织下）用**同一个登录名**检索到：

  ```bash
  # 仓库 A（XMZZUZHI/SuperNPC）由 qixiaoxin 写入
  # → 实体自动推导为 qixiaoxin（无需传 --user-id）
  python3 /app/scripts/bailian-memory.py add --content "本组织镜像构建统一走 docker.yml 复用模板"

  # 仓库 B（任何其它仓库，同一人 qixiaoxin）检索
  # → 实体同样为 qixiaoxin，无需任何额外配置即可召回上述结论
  python3 /app/scripts/bailian-memory.py search --query "镜像构建复用模板怎么用？"

  # 如需显式确认检索实体，看日志里的 user_id（或 add 时 meta_data.user_identity）
  ```

- **同一人统一检索示例**（同一个 `user-id` 贯穿所有仓库）：

  ```bash
  # 无论从哪个仓库调用，同一人的 user_id 恒为登录名本身
  python3 /app/scripts/bailian-memory.py list   # user_id=qixiaoxin
  ```

- **定时任务 / 无用户上下文**（如 `crontab`）场景下拿不到任何用户标识，会回落到组织级实体 `usr_<根组织>`，与人工触发时的「人」实体**不是同一个**（这是刻意设计：避免无人任务污染某个人的记忆线）；如需完全统一，请在密钥仓库注入 `MEMORY_USER_ID`（如 `qixiaoxin`）。

### 10.6 快速开始（5 分钟跑通，只读优先）

> 本节面向**第一次用**的读者：先用**只读**方式确认接线正常，再去看 10.7 的完整参数。
> ⚠️ **自检纪律（强制）**：确认接线**不要为验证而 `add`**——记忆库是**所有仓库共用的持久化存储**，
> 反复自检 `add` 会在共享实体上堆出重复节点、污染后续召回。默认走 `list` / `search` 只读自检；
> 仅当确有需要验证写入链路时，才用**隔离的测试实体**（显式 `--user-id`）并在验证后清理（见 四）。

#### 一、前置条件（缺一不可）

| 条件 | 检查方式 | 不满足时怎么办 |
| --- | --- | --- |
| 已注入 `DASHSCOPE_API_KEY` | `[ -n "$DASHSCOPE_API_KEY" ] && echo 已注入` | 到**密钥仓库**（如 `key/npc.yml`）注入后重跑，**不要**写死进代码 / `.cnb.yml` |
| 环境有 `python3`（≥ 3.8） | `python3 --version` | 镜像已预装（实测 3.11 系）；缺失时先补装再调用 |
| 运行时脚本就位（镜像预置） | `ls /app/scripts/bailian-memory.py` | 属运行时预置文件；缺失说明镜像异常，**不要**去被拉起仓库里找 |
| 已知触发者登录名（用于确认写入哪个实体） | `echo "$CNB_BUILD_USER"` | 为空时脚本会按 10.5 优先级继续推导，无需手工传 `--user-id` |

#### 二、两步只读跑通（推荐）

确认接线只需**读得通**：能列出、能检索，即证明「脚本就位 + 鉴权有效 + 网络可达」三件事。**无需写入。**

```bash
# 第 1 步：列出本人实体下的记忆（不传 --user-id，自动落到触发者登录名）
python3 /app/scripts/bailian-memory.py list --page-size 5
# 期望输出（列表可能为空，属正常）：
#   [memory] 列出记忆: user_id=qixiaoxin page_num=1
#   [memory] 本页 0 条记忆

# 第 2 步：语义检索（同一登录名，换任意仓库都行）
python3 /app/scripts/bailian-memory.py search --query "镜像构建复用模板怎么用"
# 期望输出（未命中属正常，长期记忆本就该「没有就返回空」）：
#   [memory] 检索记忆: user_id=qixiaoxin query='镜像构建复用模板怎么用'
#   [memory] 命中 0 条记忆
```

#### 三、接线自检（一句话判定）

- 两步都打印 `[memory] ...` 且**退出码为 0** ⇒ 接线正常，可投入使用（**命中 0 条 / 本页 0 条都算正常**）。
- 报 `未注入 DASHSCOPE_API_KEY` ⇒ 属**预期快速失败**（不裸调），到密钥仓库注入后重试即可，**不要**反复重试或中断任务（见 10.2 三、10.10）。
- 日志里 `user_id=` 不是本人登录名 ⇒ 先看 10.5 的推导优先级，再用 `--user-id` 或 `MEMORY_USER_ID`（最高优先级）显式指定。

#### 四、写入链路验证（可选，必须隔离 + 清理）

只有当只读自检**无法**排除「写入链路故障」时（例如怀疑 add 接口异常），才做这一步；**严禁**把自检数据写进默认共享实体（登录名）：

```bash
# 1) 用隔离的测试实体写入（显式 --user-id，绝不省略）
TEST_UID="conn_check_$(date +%s)"   # 形如 conn_check_1730000000，与本人实体隔离
python3 /app/scripts/bailian-memory.py add --user-id "$TEST_UID" \
  --content "接线自检占位结论，验证后请删除"
# 期望输出：
#   [memory] 写入记忆: user_id=conn_check_1730000000
#   [memory] 写入成功，变更片段 1 条
#   [memory]   [ADD] node_xxx 接线自检占位结论，验证后请删除

# 2) 即时清理：用上一步输出的 memory_node_id 删除该节点（delete 不可恢复，务必先用 search/list 确认 node_id）
python3 /app/scripts/bailian-memory.py search --user-id "$TEST_UID" --query "接线自检占位"
python3 /app/scripts/bailian-memory.py delete --user-id "$TEST_UID" --node-id <上一步返回的 node_id>
# 期望输出：
#   [memory] 删除成功
```

- **隔离实体必须带 `--user-id`**：省略会回落到本人登录名，等于往共享记忆线写垃圾，违反 10.10「先查后写 / 跨仓库共享勿破坏」。
- **验证即清理**：删除不可恢复，删前先用 `search` / `list` 确认 `node_id` 指向正确；确认清理干净后再结束自检。
- **不得把 `conn_check_*` 之类的临时结论长期留在库里**，避免污染后续召回。

### 10.7 用法与参数速查（优先复用脚本，勿手写 curl 样板）

脚本为**零依赖**（仅标准库），签名与参数校验已内置，直接调用即可。

> 提示：`--user-id` **一般无需手写**，省略时会自动推导为**触发者登录名**（如 `qixiaoxin`，同一个人在所有仓库共用同一 user-id，详见 10.5）。下方示例中的 `--user-id user_001` 仅为展示显式传参写法。

#### 一、子命令与参数总览

| 子命令 | 作用 | 必填参数 | 可选参数 |
| --- | --- | --- | --- |
| `add` | 添加记忆 | `--message ROLE:CONTENT`（可重复）或 `--content`（二者**互斥**） | `--user-id`、`--profile-schema`、`--project-id`、`--memory-library-id`、`--meta-data` |
| `search` | 语义检索 | `--query` | `--user-id`、`--max-results`（1~100，默认 10）、`--rewrite`（默认 true）、`--rerank`（默认 true）、`--similarity-threshold`（0.0~1.0，默认 0.6）、`--plan-version`（`Pro`/`Lite`，**大小写敏感**，默认 Pro）、`--memory-library-id` |
| `list` | 分页列出 | 无 | `--user-id`、`--page-size`（默认 10）、`--page-num`（默认 1）、`--memory-library-id` |
| `update` | 更新片段内容 | `--node-id` | `--user-id`、`--content` |
| `delete` | 删除片段（不可恢复） | `--node-id` | `--user-id` |
| 全局 | — | — | `--json`（额外输出完整 JSON 响应）、`-h` |

参数与脚本 `build_parser()` **逐项对齐**，改动能以 `python3 /app/scripts/bailian-memory.py <子命令> --help` 为准。

> 取值细节：`--rewrite` / `--rerank` 为布尔参数，接受 `true/false`、`1/0`、`yes/no`（**大小写不敏感**）；`--plan-version` 仅接受 `Pro` / `Lite`（**大小写敏感**）。

#### 二、常用命令示例

```bash
# 添加记忆：对话形式（最多 50 条消息，role 仅支持 user / assistant）
python3 /app/scripts/bailian-memory.py add --user-id user_001 \
  --message user:"每天上午9点提醒我喝水" --message assistant:"好的，已记录"

# 添加记忆：自定义内容形式（与 --message 互斥，max 512 字符）
python3 /app/scripts/bailian-memory.py add --user-id user_001 --content "用户偏好用 Python 3.12 与 PEP 8 风格"

# 搜索记忆：语义检索（默认开启改写与重排，相似度阈值 0.6）
python3 /app/scripts/bailian-memory.py search --user-id user_001 --query "我需要做什么？" --max-results 10

# 列出记忆：分页查看
python3 /app/scripts/bailian-memory.py list --user-id user_001 --page-size 10 --page-num 1

# 更新 / 删除记忆：需先拿到 memory_node_id
python3 /app/scripts/bailian-memory.py update --user-id user_001 --node-id NODE_ID --content "还要提醒我10点吃药"
python3 /app/scripts/bailian-memory.py delete --user-id user_001 --node-id NODE_ID

# 需要完整响应体时追加 --json（便于解析 memory_node_id）
python3 /app/scripts/bailian-memory.py --json search --user-id user_001 --query "我的偏好？"
```

#### 三、输出格式（敲完能看到什么）

- **默认**：只打印人类可读摘要，行首统一带 `[memory]` 前缀，便于在日志里过滤。
  - `add` → `[memory] 写入记忆: user_id=...` / `[memory] 写入成功，变更片段 N 条` / 逐条 `[memory]   [ADD] <memory_node_id> <content>`（`event` 取值为 `ADD`/`UPDATE`/`DELETE`）。
  - `search` → `[memory] 检索记忆: ...` / `[memory] 命中 N 条记忆` / 逐条 `<memory_node_id> <content>`。
  - `list` → `[memory] 列出记忆: ...` / `[memory] 本页 N 条记忆` / 逐条 `<memory_node_id> <content>`。
  - `update` / `delete` → 打印 `更新成功` / `删除成功`。
- **`--json`**：在上述摘要后追加完整 JSON（`ensure_ascii=False`，中文不转义），形如：

  ```json
  {
    "request_id": "req-xxx",
    "memory_nodes": [
      { "memory_node_id": "node_xxx", "content": "…", "event": "ADD" }
    ]
  }
  ```

- **怎么拿 `memory_node_id` 做后续 update/delete**：`add` / `search` / `list` 的默认摘要里**每行第二列**就是它；需要结构化解析时用 `--json` 取 `memory_nodes[].memory_node_id`。

#### 四、端到端闭环示例（写 → 查 → 改 → 删）

```bash
# ① 写入
python3 /app/scripts/bailian-memory.py add --content "GPG 签名 unknown_key 需把公钥登记到平台"
# ② 召回（拿到 memory_node_id，假设为 node_abc）
python3 /app/scripts/bailian-memory.py search --query "GPG unknown_key 怎么处理"
# ③ 内容纠偏（用 ② 拿到的 node_abc）
python3 /app/scripts/bailian-memory.py update --node-id node_abc --content "GPG 签名 unknown_key：需重新登记公钥后再提交"
# ④ 结论失效时删除（不可恢复，删前先 search 确认 node_id）
python3 /app/scripts/bailian-memory.py delete --node-id node_abc
```

#### 五、取值回落与退出码

- **退出码**：`0` 成功；`1` 调用失败（鉴权缺失 / 网络异常 / 业务错误）；`2` 参数错误（含超长、互斥、缺必填校验）。
- `--user-id` 省略时回落到 `MEMORY_USER_ID` → **触发者登录名**（`CNB_BUILD_USER`/`CNB_COMMITTER`，如 `qixiaoxin`）→ 无人上下文才用 `usr_<根组织>`；`--project-id` / `--profile-schema` 同理回落到对应环境变量。**默认即跨仓库共享**，无需每个仓库单独配置。
- **记忆库 ID 已写死**：脚本内置 `DEFAULT_MEMORY_LIBRARY_ID = "22fcd3f37eee42d6ac99cf25d03ac6c3"`，所有接口默认携带该记忆库，**无需每次传参**；仅需临时切库时用 `--memory-library-id` 或 `MEMORY_LIBRARY_ID` 显式覆盖（显式优先级最高）。
- **`meta_data` 自动注入**：`add` 时脚本自动把仓库溯源信息合并进 `meta_data`（仅在能取到对应环境变量时注入）：

  | 键 | 含义 | 取值来源 |
  | --- | --- | --- |
  | `repo_slug` | 完整仓库路径，用于回溯来源仓库 | `CNB_REPO_SLUG` |
  | `repo_scope` | 根组织 slug，用于按组织辅助过滤 | `CNB_ROOT_SLUG` / `CNB_GROUP_SLUG` |
  | `user_identity` | 人的稳定登录名，便于检索后确认归属人 | 同 `user_id` 的推导结果 |

  合并规则：**自动注入在前、`--meta-data` 显式指定在后（显式覆盖自动值）**；用 `MEMORY_AUTO_META_DATA=0` 可整体关闭自动注入。

### 10.8 常见报错与排错

| 现象 | 真实报错文案（stderr，带 `[memory] 错误:` 前缀） | 退出码 | 处置 |
| --- | --- | --- | --- |
| 未注入 API Key | `未注入 DASHSCOPE_API_KEY，无法调用百炼记忆库 API。请在密钥仓库（如 key/npc.yml）中注入该变量后重试。` | 1 | 属**预期快速失败**（不裸调）；去密钥仓库注入后重试，**不要**反复重试或中断任务 |
| 无法推导实体 | `缺少 --user-id（记忆实体 ID）：未显式传参，且环境变量 … 均为空，无法推导默认实体` | 2 | 显式传 `--user-id`，或注入 `MEMORY_USER_ID` / 用户类环境变量 |
| `user_id` 超长 | `--user-id 超长（N > 64 字符）` | 2 | 截短到 ≤ 64 字符 |
| 内容与对话混传 | `--content 与 --message 互斥，请二选一` | 2 | 二者只留一个（填 `--content` 时服务端会忽略 `messages`） |
| `add` 什么都没给 | `必须提供 --message（对话）或 --content（自定义内容）之一` | 2 | 至少给一种写入形式 |
| 内容超长 | `--content 超长（N > 512 字符）` | 2 | 拆成多条结论分别写入 |
| 消息条数超限 | `消息条数超限（N > 50 条）` | 2 | 精简对话条数 |
| `--message` 格式错 | `--message 格式错误（应为 role:content）: <原文>` | 2 | 用 `user:` / `assistant:` 前缀；正文含冒号不影响（只按**第一个**冒号切分） |
| 429 限流 / 5xx | 由脚本自动 **1s / 2s / 4s 指数退避重试，最多 3 次**，仍失败才报错 | 1 | 等退避结束即可；持续失败看返回值里的 `request_id` 排查 |
| 4xx（非限流） | 参数 / 鉴权问题，**快速失败不重试** | 1 | 按 `code` / `message` 修正入参或凭证 |
| 响应非 JSON | `调用 <METHOD> <path> 返回非 JSON 响应，无法解析` | 1 | 属服务端异常，重试无意义；保留原文与 `request_id` 上报 |
| 重试耗尽 | `调用 <METHOD> <path> 失败: <最后一次错误>`（HTTP 错误带 `request_id`；网络异常为 `网络异常: <reason>`） | 1 | 结合 `request_id` / 原因定位；记忆失败**不阻断**主流程 |

> 排错纪律：日志中只保留 `user_id` / `memory_node_id` / `request_id` 等**非敏感**字段，**严禁**把 `DASHSCOPE_API_KEY` 原文贴进评论或日志。

### 10.9 Agent 接入清单（把记忆用起来的落地步骤）

1. **首次使用 / 排查接线**：**用只读方式验证接线，不要为自检而 `add`**——接线是否正常只需证明「能检索、能连通」，跑一次 `list`（或 `search`）返回 `[memory] ...` 且退出码为 0 即为正常，详见 10.6 三。若确需验证写入链路，必须使用**隔离的测试实体**（显式 `--user-id`，如 `conn_check_<时间戳>`）并在验证后按 10.6 四 清理；**严禁**把自检示例结论写入默认共享实体（登录名）而留下垃圾节点。若报鉴权缺失属预期，按 10.2 三 跳过记忆环节继续任务。
2. **任务开始**：判断本次是否属 10.2 一 的 5 类触发场景；命中则先跑一次 `search`（`--query` 用任务关键词或用户原话）。
3. **收到结果**：命中则把历史结论作为**先验**采纳（若与现状冲突，以现状为准并走第 5 步纠偏）；未命中则按常规流程继续，**不重试、不报错**。
4. **任务收尾**：判断是否产出 10.2 二 的 4 类可复用结论；有则 `add` 一条（`--content` ≤ 512 字符，讲清「结论 + 适用场景」）。
5. **已存在同结论**：用 `update` 补充（先 `search` 拿 `memory_node_id`），**不要**重复 `add` 制造重复片段；结论已被推翻则 `update` 修正。
6. **失败兜底**：任一记忆调用报错 → 打一条告警日志后**继续任务**，绝不因记忆库不可用而中断 NPC 主流程。

### 10.10 使用纪律（强制）

- **凭证不入库**：`DASHSCOPE_API_KEY` 只能来自密钥仓库注入，**禁止**写死进代码、`.cnb.yml`、文档或评论。
- **写入前先脱敏**：记忆库是持久化存储且会被语义检索召回，**严禁**写入 Token、密钥、用户隐私、未脱敏的内部链接等敏感信息；只写入可复用的结论性知识（如业务约定、排查经验、用户明确偏好）。
- **删除不可恢复**：`delete` 无回收站，执行前必须先 `search` / `list` 确认 `memory_node_id` 指向正确，**不要**凭猜测删除。
- **先查后写**：写入前先 `search` 确认是否已有同结论，避免重复片段；同结论用 `update` 而非再 `add`。
- **不滥用为日志仓**：记忆片段面向「长期可复用语义记忆」，不要把逐次任务流水当作记忆写入，避免污染检索结果。
- **失败不阻断主流程**：记忆读写属**增强能力**，调用失败（尤其鉴权缺失）时应告警并继续完成任务，**不得**因记忆库不可用而中断 NPC 主流程。
- **跨仓库共享勿破坏**：`user_id` 会被**所有仓库**共用，写入时须确保是「跨仓库可复用」的结论性知识（平台约定、排查经验、通用规范）；仓库特有的临时信息请写进 `meta_data` 或不要入库，避免污染其它仓库的检索结果。
- **自检不得污染共享记忆线**：接线核对 / 排障自检**默认只读**（`list` / `search`），**禁止**为「验证接线」而把示例结论 `add` 进默认共享实体（登录名）；确需验证写入链路时，必须用隔离的测试实体（显式 `--user-id`，如 `conn_check_<时间戳>`）并在验证后 `delete` 清理（见 10.6 四）。共享库是所有仓库共用的持久化存储，重复的自检写入会堆出重复节点、挤占召回名额。
- **勿给 `user_id` 加组织/仓库前缀**：`user_id` 统一为登录名本身（如 `qixiaoxin`），**禁止**改写成 `usr_<根组织>/<登录名>`、`<组织>_<登录名>` 或拼接 `repo_slug` 等形态，否则同一人会被拆成多个实体，「一个 user-id 检索全部记录」失效。
- **文档与脚本同源**：本章参数表 / 示例 / 报错文案均须与 `/app/scripts/bailian-memory.py` 保持一致；改脚本时同步改文档（以 `--help` 为准）。

---

## 11. 本项目技术上下文（astrbot_plugin_models_ai）

> 本章内容描述**本仓库实际代码**（项目概览 / 目录结构 / 架构 / 指令 / 约定 / 开发环境），供 Agent 快速建立项目认知。
> 原先独立存在的 `AGENT.md` 已合并至此，**不再保留该文件**（`AGENT.md` 与 `AGENTS.md` 仅差一个字母，易被误判为重复文件）。

### 11.1. 项目概览

| 项目 | 说明 |
| --- | --- |
| 名称 | `astrbot_plugin_models_ai` |
| 类型 | AstrBot 插件（Python） |
| 版本 | v0.0.7 |
| 作者 | 祁筱欣 |
| Python | 3.12+（CI 使用 black/flake8，声明 3.12+；pre-commit 中 black 指定 3.11） |
| 上游 API | Gitee AI（`https://ai.gitee.com/v1`，OpenAI 兼容接口） |
| 主要依赖 | `aiofiles`, `aiohttp`, `openai`, `deprecated`（另用 `httpx`） |

插件把 Gitee AI 的多模态生图能力封装为 AstrBot 指令 + LLM 工具，支持提示词比例解析、多 API Key 轮询、请求防抖、图片自动清理。

---

### 11.2. 目录结构

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
└── install_gpg_keys.sh     # GPG 签名环境安装脚本
```

---

### 11.3. 核心架构与数据流

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

### 11.4. 指令与 LLM 工具

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

### 11.5. 关键约定

- **配置**：全部走 `_conf_schema.json`，代码内默认值集中在 `core/config.py`（`DEFAULT_BASE_URL/MODEL/SIZE/...`），不要在业务代码里散落硬编码。
- **多 Key 轮询**：`GiteeAIClient._get_next_api_key()` 按索引轮询；`parse_api_keys` 兼容字符串与列表配置。
- **错误处理**：API 层将 OpenAI 异常转换为中文 `RuntimeError`（认证/限流/500/未知），命令层捕获后回包友好信息。
- **防抖常量**：`DEBOUNCE_SECONDS=10`、`MAX_CACHED_IMAGES=20`、`OPERATION_CACHE_TTL=300`、`CLEANUP_INTERVAL=10`（每 N 次生成触发一次清理）。
- **Debug 日志**：各组件均实现 `debug_log()`，受 `debug_mode` 开关控制，统一前缀如 `[GiteeAIClient]`、`[RateLimiter]`。
- **异步优先**：所有 I/O 使用 async/await，会话与客户端复用（勿在请求内重复创建 ClientSession）。
- **类型与文档**：函数使用类型注解，docstring 遵循 Google 风格（pydocstyle `--convention=google`），中文注释与说明。

---

### 11.6. 开发环境

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

### 11.7. 代码质量与提交规范

#### 11.7.1 提交前自检（pre-commit）

仓库配置了 `.pre-commit-config.yaml`，提交前请执行：

```bash
pre-commit install
pre-commit run --all-files
```

包含：`gitleaks`、`shellcheck`、`black`、`flake8`（max-line-length=100，忽略 E203/W503）、`isort`（profile=black）、`mypy`（ignore-missing-imports）、`pydocstyle`（google）、以及基础文件检查。

#### 11.7.2 代码风格

- `black` 格式化，`isort --profile black` 排序 import。
- 行宽上限 100（flake8），类型注解 + Google 风格 docstring。
- 文件结尾保留换行，禁止尾随空格，统一 LF。

#### 11.7.3 Commit 规范（Conventional Commits）

沿用仓库历史风格：`feat` / `fix` / `docs` / `chore` / `refactor` 等，中文描述。
示例：`fix(gpg): 同步 install_gpg_keys.sh 至 MZAPI 规范版本`、`docs: 添加图像分析功能文档`。

#### 11.7.4 分支与 PR

1. Fork / 从 `main` 拉出特性分支。
2. 完成后提交 PR，说明变更点与验证方式。
3. 面向 Issue 自动化的工作流：`issue-killer.yml`、`pr-review.yml`、`pr-review-killer.yml` 等。

---

### 11.8. CI / 自动化（`.github/workflows/`）

| Workflow | 作用 |
| --- | --- |
| `CodeQL.yml` | 代码安全分析 |
| `security-scan.yml` / `DevSkim.yml` / `secret-scanning.yml` | 安全与密钥扫描 |
| `PythonDependencyAudit.yml` / `dependency-review.yml` | 依赖审计与依赖变更审查 |
| `tfsec.yml` | IaC 安全扫描 |
| `Scorecard.yml` | 供应链安全评分 |
| `inclusiveness-analyzer.yml` | 包容性分析 |
| `stale.yml` | 陈旧 Issue / PR 自动化 |
| `release.yml` | 发布流程 |
| `coverage.yml` | 单元测试覆盖率统计并上报 Codecov（`main` push / PR） |

`.cnb.yml`：CNB 流水线在 `main` 分支 push 时同步代码到 GitHub 上游仓库。

> **OSSAR 工作流已移除（`ossar.yml`）**：上游 `github/ossar-action` 停更在 v2.0.0（2024-04），
> 其 `action.yml` 固定为 `node20`、内置 `@actions/core@1.2.6` 仍使用已废弃的 `set-output` 命令，
> 因此持续产生「Node.js 20 弃用」与「`set-output` 弃用」两条告警，且**上游无 Node 24 版本可升**。
> 其能力（静态安全分析）已由 `CodeQL.yml`（Python 语义级分析，主运行器矩阵覆盖三平台三版本）、
> `DevSkim.yml`（多版本源码模式扫描）与 `security-scan.yml`（Bandit）完整覆盖，
> 故直接移除该工作流以根治告警，避免为消警而长期背负一个无人维护的 Action。

#### 11.8.1 覆盖率链路（Codecov 单一来源）

覆盖率上报**只有一条链路**：GitHub 侧的 `.github/workflows/coverage.yml` + `codecov.yml`，在 GitHub `push`(main) / `pull_request` 时产出 `coverage.xml` 并上报 Codecov，徽章展示在 README 顶部。

> **CNB 侧（`.cnb.yml`）原有的「覆盖率测试 + `testing:coverage`」作业已移除**，CNB 平台不再产出覆盖率徽章，`.cnb.yml` 仅保留「同步到 GitHub」作业。新增/修改覆盖率链路时**不要**再往 CNB 侧加回上报，统一走 Codecov。

**GitHub 侧关键约定（改动前务必先读这条，否则徽章会显示 unknown）：**

- 覆盖率必须用**包名**计数：`python -m coverage run --source=astrbot_plugin_models_ai -m pytest tests -q`。
  - 仓库目录名不等于包名，靠 `ln -sfn "$GITHUB_WORKSPACE" "$RUNNER_TEMP/astrbot_plugin_models_ai"` 铺出可导入的包视图（与 `tests/_coverage_support.py` 的垫片同源）。
  - **不要**改用「绝对路径 `--source=/workspace`」的写法：Codecov 侧用绝对路径会写出 `/home/runner/work/...`，固定路径映射后匹配不到文件，覆盖率恒为 0。
- 报告格式固定为 `coverage.xml`（`coverage xml`），`codecov.yml` 中的 `flags.unittests.paths` 与之一致。
- **`CODECOV_TOKEN` 只能来自密钥注入**：读取仓库 Secret `secrets.CODECOV_TOKEN`。**严禁**写进代码、`.cnb.yml`、文档或评论。
- 未配置 token 时上报步骤 `continue-on-error` 跳过，CI **不失败**（仅留存 `coverage-xml` 工件），属预期行为。
- **令牌口径以 Codecov 官方规则为准，本仓库固定「显式携带 `secrets.CODECOV_TOKEN`」**（依据 Codecov 官方 *When do I need a token?* 一节）：
  - **私有仓库**：**所有**上传都必须携带令牌。
  - **公开仓库**：仅当「上传针对**受保护分支**（如 `main`）的提交」且「仓库所有者**未**关闭公开仓库的令牌校验」时才要求令牌；未被保护的提交（如 `pr300:main` 这类带前缀的分支）可免令牌。
  - **本仓库的 GitHub 目标是公开仓库**（实测 `xiaomizhoubaobei/astrbot_plugin_models_ai` 的 API 返回 `private: false` / `visibility: public`；「私有」指的只是 CNB → GitHub 的**同步链路**，不是目标仓库属性，二者不要混为一谈）；而路线上的 `coverage.yml` 恰好在 `push: main` 这一**受保护分支**上上传，且我们**不打算**去 Codecov 后台关闭公开仓库令牌校验 → 走到「公开 + 受保护分支 + 未关闭校验」这一格，**依然必须带令牌**。
  - 结论：无论仓库公开还是私有，本仓库都固定走「显式带 `secrets.CODECOV_TOKEN`」这条路径，**不要**改用免令牌上传，也不要因为目标是公开仓库就以为可以省掉 Secret。
- Codecov 后台提示所提及的「无令牌上传」开关需 `codecov-action` **> v5.0** / `codecov-cli` **> v0.9** 才生效，且官方声明该路径共享全局限流、超限即上传失败且不贴状态，**不建议依赖**。本仓库固定走「显式带令牌」路径（`codecov-action@v5` + `env: CODECOV_TOKEN`）。
- `codecov.yml` 的 `project` / `patch` 门禁目前均为 `informational: true`（只提示不卡 PR）；要收紧时改这两处，而不是在 CI 里加 `--fail-under`。

**完成 Codecov 接线后仍需人工做一步**：打开 <https://codecov.io> 用 GitHub 账号授权本仓库，先让 CI 成功上报一次，徽章才会从 unknown 变为真实百分比。

---

### 11.9. Agent 工作指引

1. **先读配置再动手**：涉及新配置项时同步更新 `_conf_schema.json` 与 `core/config.py`。
2. **保持分层**：命令逻辑放 `commands/`，可复用能力放 `core/`，上游 API 调用放 `gitee/`，LLM 工具放 `llm_tools/`。
3. **复用基础设施**：防抖统一用 `core/command_utils.check_rate_limit`，比例解析统一用 `parse_prompt_and_size`。
4. **新增指令**：在 `main.py` 的 `ai_gitee_group` 注册，并在 `commands/` 与 `commands/__init__.py` 中实现/导出。
5. **新增风格**：只改 `commands/style_prompts.json`，不写死代码。
6. **提交前**：运行 `pre-commit run --all-files`，确认 black/flake8/mypy 通过。
7. **提交信息**：使用 Conventional Commits 中文描述。
8. **不要把密钥写进代码或文档**；API Key 与 `CODECOV_TOKEN` 一律通过配置 / 密钥注入。
9. **改覆盖率链路**：覆盖率统一由 `.github/workflows/coverage.yml` 上报 Codecov，CNB 侧上报已移除；改动前先读 10.8.1，确认 `--source` 写法与报告格式未被破坏。

---

### 11.10. 参考文档

- `README.md` — 项目介绍与文档导航
- `docs/DEVELOPMENT_GUIDE.md`、`docs/COMPLETE_DEVELOPER_GUIDE.md` — 开发/架构指南
- `docs/FUNCTIONS_OVERVIEW.md` — 完整功能总览
- `docs/IMPLEMENTATION_ROADMAP.md` — 实现路线图
- `CONTRIBUTING.md`、`CODE_OF_CONDUCT.md` — 贡献与社区规范
