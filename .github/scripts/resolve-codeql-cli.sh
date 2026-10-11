#!/usr/bin/env bash
# =============================================================================
# 解析可执行的 CodeQL CLI 路径（供 AI 审计工作流复用）
# =============================================================================
# 背景：审计流程需要用 CodeQL CLI 本地建库，但 CLI 的安装位置随 runner 不同而
#       不同——托管 runner 可能装在**带版本号的 tool-cache 路径**（如
#       /opt/hostedtoolcache/codeql/3.19.0/x64/codeql），自托管 runner 可能在
#       /opt/codeql 或仅在 PATH 里，甚至压根没装。
#
# 旧实现只探测「一个写死的固定路径 + PATH」，命中不了上述位置时会直接 exit 1，
#       导致整个审计在建库前中断。本脚本把探测面收敛为**多候选 + 兜底安装**：
#       ① 显式指定的 CODEQL_CLI 环境变量（最高优先级，允许人工覆盖）；
#       ② 一系列已知安装位置（含带版本号的 tool-cache 目录）；
#       ③ PATH 上的 codeql；
#       ④ 都没有时，下载官方固定版本的 CodeQL bundle，**先做 SHA-256 完整性校验**
#          再解压到临时目录（校验不通过即拒绝执行，防止「解压即执行」供应链风险）。
#
# ⚠️ 【路径规范化】凡是经 `command -v` 得到的路径，**必须**转成绝对路径再返回：
#       PATH 中若含**相对条目**（如 `bin`、`./tools`——登录 shell / 自托管 runner
#       的常见配置），`command -v codeql` 会原样返回 `bin/codeql` 这种**相对路径**。
#       该相对路径只在「当前工作目录」下成立，而工作流后续步骤（如
#       `working-directory: seclab-taskflow-agent` 的审计步与 codeql toolbox）
#       的 cwd 与本脚本不同，同一个相对字符串在那边解析不到 → CLI 失效。
#       故统一用 _canonicalize 归一化为绝对路径后再对外返回、再写入 GITHUB_ENV。
#
# 用法：source 本脚本后调用 resolve_codeql_cli，结果写入全局变量 CODEQL_CLI
#       （同时打印到 stdout，便于调用方直接捕获）。
# 退出码：0 = 解析成功；1 = 全部候选与兜底均失败（调用方应据此失败退出）。
# =============================================================================

# 兜底安装的 CodeQL bundle 版本与下载源（固定版本 + 校验，避免浮动 tag 漂移）
CODEQL_BUNDLE_VERSION="${CODEQL_BUNDLE_VERSION:-v2.19.3}"
CODEQL_BUNDLE_URL_DEFAULT="https://github.com/github/codeql-action/releases/download/codeql-bundle-${CODEQL_BUNDLE_VERSION}/codeql-bundle-linux64.tar.gz"

# 与上述固定版本严格对应的 bundle SHA-256（linux64）。
# 下载后必须校验通过才会解压执行；缺少或校验失败一律拒绝，避免「解压即执行」的供应链风险。
# 升级 CODEQL_BUNDLE_VERSION 时必须同步更新此摘要，否则兜底安装会主动失败（fail-closed）。
CODEQL_BUNDLE_SHA256_DEFAULT="af1d57cac9b91afcc36604ca4d5bb4ac477a32ff9ee7e1ee2cb3b64be47fcb50"

# 判断给定路径是否为可执行的 CodeQL CLI（文件存在且可执行）
_is_codeql_cli() {
  [ -n "${1:-}" ] && [ -x "$1" ] && [ -f "$1" ]
}

# 把路径归一化为**绝对路径**（相对路径按当前工作目录展开）。
# 依赖 readlink -f（GNU coreutils 提供，runner 上必有）；不可用时回落到
# `cd "$(dirname)" && pwd` 手工拼接，二者都失败则原样返回（由调用方兜底）。
# $1 = 待归一化的路径（可为相对或绝对）
_canonicalize() {
  local p="${1:-}" abs
  [ -n "$p" ] || return 1
  # 已是绝对路径且能直接解析时，优先用 readlink -f 消解符号链接与 `..`
  if abs="$(readlink -f -- "$p" 2>/dev/null)" && [ -n "$abs" ]; then
    printf '%s\n' "$abs"
    return 0
  fi
  # 回落：拼绝对路径（不消解符号链接，但至少锚定到 cwd，避免相对路径漂移）
  if [ -e "$p" ]; then
    case "$p" in
      /*) printf '%s\n' "$p" ;;
      *) printf '%s\n' "$(pwd)/$p" ;;
    esac
    return 0
  fi
  return 1
}

# 对外公开的路径归一化入口：把（可能是相对的）路径转成**绝对路径**。
# 供调用方在写入 GITHUB_ENV 等「跨 cwd 传递」的场景前显式调用，
# 即使不经过 resolve_codeql_cli 也能拿到规范化结果。
# $1 = 待归一化的路径；成功打印绝对路径并返回 0，失败返回非零。
canonicalize_path() {
  _canonicalize "${1:-}"
}

# 校验给定文件的 SHA-256 是否与期望摘要一致（大小写不敏感）
# $1 = 文件路径；$2 = 期望的 SHA-256（64 位十六进制）。摘要为空视为校验失败。
_verify_sha256() {
  local file="${1:-}" expected="${2:-}" actual
  if [ ! -f "$file" ]; then
    echo "ERROR: 待校验文件不存在：${file}" >&2
    return 1
  fi
  if [ -z "$expected" ]; then
    echo "ERROR: 未提供期望的 SHA-256 摘要，拒绝执行未校验的 bundle。" >&2
    return 1
  fi
  # sha256sum 在 GNU coreutils / busybox 中均可用；取首列作为实际摘要
  actual="$(sha256sum "$file" 2>/dev/null | awk '{print $1}')"
  if [ -z "$actual" ]; then
    echo "ERROR: 无法计算 ${file} 的 SHA-256（缺少 sha256sum？）。" >&2
    return 1
  fi
  if [ "$(printf '%s' "$actual" | tr 'A-F' 'a-f')" != "$(printf '%s' "$expected" | tr 'A-F' 'a-f')" ]; then
    echo "ERROR: CodeQL bundle 完整性校验失败。" >&2
    echo "  期望 SHA-256: ${expected}" >&2
    echo "  实际 SHA-256: ${actual}" >&2
    return 1
  fi
  echo "CodeQL bundle 完整性校验通过（SHA-256: ${actual}）。" >&2
  return 0
}

# 在候选列表中返回第一个可用的 CLI 路径（找不到则返回非零）
# ⚠️ 返回前一律经 _canonicalize 归一化为绝对路径（理由见文件头注释）。
_probe_known_locations() {
  local cand abs
  # ① 显式指定优先
  if _is_codeql_cli "${CODEQL_CLI:-}"; then
    if abs="$(_canonicalize "$CODEQL_CLI")"; then
      printf '%s\n' "$abs"
      return 0
    fi
  fi

  # ② 已知安装位置（含带版本号的 tool-cache 路径，逐项探测）
  for cand in \
    /opt/hostedtoolcache/codeql/current/codeql \
    /opt/hostedtoolcache/codeql/*/x64/codeql/codeql \
    /opt/hostedtoolcache/codeql/*/*/codeql/codeql \
    /opt/codeql/codeql \
    /opt/codeql \
    /usr/local/bin/codeql \
    /usr/bin/codeql ; do
    # 通配符未匹配时，cand 会保留字面量；交由 _is_codeql_cli 判定即可
    if _is_codeql_cli "$cand"; then
      if abs="$(_canonicalize "$cand")"; then
        printf '%s\n' "$abs"
        return 0
      fi
    fi
  done

  # ③ PATH 上的 codeql
  # ⚠️ 【务必规范化】PATH 含相对条目时，command -v 会返回相对路径（如 bin/codeql）；
  #    直接返回会让下游步骤（cwd 不同）解析不到，故此处强制转绝对路径。
  cand="$(command -v codeql 2>/dev/null || true)"
  if _is_codeql_cli "$cand"; then
    if abs="$(_canonicalize "$cand")"; then
      printf '%s\n' "$abs"
      return 0
    fi
    # 规范化失败时宁可**不返回**相对路径（返回它等于埋雷），继续往下找兜底
    echo "WARN: 命中的 codeql（${cand}）无法归一化为绝对路径，忽略该候选。" >&2
  fi

  return 1
}

# 兜底：下载并解压官方 CodeQL bundle，返回解压后的 CLI 路径
_install_codeql_fallback() {
  local dest url sha256 abs
  dest="${CODEQL_HOME:-/tmp/codeql-bundle}"
  url="${CODEQL_BUNDLE_URL:-$CODEQL_BUNDLE_URL_DEFAULT}"
  # 期望摘要：默认取自与固定版本绑定的常量；仅当人工显式指定 bundle 时，
  # 才允许通过 CODEQL_BUNDLE_SHA256 覆盖，二者必须配套使用。
  sha256="${CODEQL_BUNDLE_SHA256:-$CODEQL_BUNDLE_SHA256_DEFAULT}"

  # 已解压过则直接复用（幂等，便于重跑）；同样归一化为绝对路径
  if _is_codeql_cli "${dest}/codeql/codeql"; then
    if abs="$(_canonicalize "${dest}/codeql/codeql")"; then
      printf '%s\n' "$abs"
      return 0
    fi
  fi

  echo "未在已知位置找到 CodeQL CLI，尝试下载固定版本 bundle：${url}" >&2
  mkdir -p "$dest"
  if ! curl -fsSL "$url" -o "${dest}/codeql-bundle.tar.gz"; then
    echo "ERROR: CodeQL bundle 下载失败（${url}）。" >&2
    return 1
  fi
  # 先校验完整性再解压执行：摘要不匹配 / 缺失时直接拒绝，绝不落盘执行未校验内容
  if ! _verify_sha256 "${dest}/codeql-bundle.tar.gz" "$sha256"; then
    echo "ERROR: 校验未通过，拒绝解压执行 bundle。" >&2
    rm -f "${dest}/codeql-bundle.tar.gz"
    return 1
  fi
  tar -xzf "${dest}/codeql-bundle.tar.gz" -C "$dest" || {
    echo "ERROR: CodeQL bundle 解压失败。" >&2
    return 1
  }
  if _is_codeql_cli "${dest}/codeql/codeql"; then
    if abs="$(_canonicalize "${dest}/codeql/codeql")"; then
      printf '%s\n' "$abs"
      return 0
    fi
    # 兜底的 dest 默认是 /tmp 下的绝对路径；走到这里说明 dest 被人为改成相对路径
    printf '%s\n' "${dest}/codeql/codeql"
    return 0
  fi

  echo "ERROR: 兜底安装后仍未找到可执行的 CodeQL CLI。" >&2
  return 1
}

# 主入口：按「已知位置 → 兜底安装」顺序解析，成功时导出**绝对路径**的 CODEQL_CLI
resolve_codeql_cli() {
  local cli
  if cli="$(_probe_known_locations)"; then
    export CODEQL_CLI="$cli"
    printf '%s\n' "$cli"
    return 0
  fi

  if cli="$(_install_codeql_fallback)"; then
    export CODEQL_CLI="$cli"
    printf '%s\n' "$cli"
    return 0
  fi

  export CODEQL_CLI=""
  return 1
}
