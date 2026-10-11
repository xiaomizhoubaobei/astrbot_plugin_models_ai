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
#       ④ 都没有时，下载官方固定版本的 CodeQL bundle 并解压到临时目录。
#
# 用法：source 本脚本后调用 resolve_codeql_cli，结果写入全局变量 CODEQL_CLI
#       （同时打印到 stdout，便于调用方直接捕获）。
# 退出码：0 = 解析成功；1 = 全部候选与兜底均失败（调用方应据此失败退出）。
# =============================================================================

# 兜底安装的 CodeQL bundle 版本与下载源（固定版本 + 校验，避免浮动 tag 漂移）
CODEQL_BUNDLE_VERSION="${CODEQL_BUNDLE_VERSION:-v2.19.3}"
CODEQL_BUNDLE_URL_DEFAULT="https://github.com/github/codeql-action/releases/download/codeql-bundle-${CODEQL_BUNDLE_VERSION}/codeql-bundle-linux64.tar.gz"

# 判断给定路径是否为可执行的 CodeQL CLI（文件存在且可执行）
_is_codeql_cli() {
  [ -n "${1:-}" ] && [ -x "$1" ] && [ -f "$1" ]
}

# 在候选列表中返回第一个可用的 CLI 路径（找不到则返回非零）
_probe_known_locations() {
  # ① 显式指定优先
  if _is_codeql_cli "${CODEQL_CLI:-}"; then
    printf '%s\n' "$CODEQL_CLI"
    return 0
  fi

  # ② 已知安装位置（含带版本号的 tool-cache 路径，逐项探测）
  local cand
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
      printf '%s\n' "$cand"
      return 0
    fi
  done

  # ③ PATH 上的 codeql
  cand="$(command -v codeql 2>/dev/null || true)"
  if _is_codeql_cli "$cand"; then
    printf '%s\n' "$cand"
    return 0
  fi

  return 1
}

# 兜底：下载并解压官方 CodeQL bundle，返回解压后的 CLI 路径
_install_codeql_fallback() {
  local dest url
  dest="${CODEQL_HOME:-/tmp/codeql-bundle}"
  url="${CODEQL_BUNDLE_URL:-$CODEQL_BUNDLE_URL_DEFAULT}"

  # 已解压过则直接复用（幂等，便于重跑）
  if _is_codeql_cli "${dest}/codeql/codeql"; then
    printf '%s\n' "${dest}/codeql/codeql"
    return 0
  fi

  echo "未在已知位置找到 CodeQL CLI，尝试下载固定版本 bundle：${url}" >&2
  mkdir -p "$dest"
  if ! curl -fsSL "$url" -o "${dest}/codeql-bundle.tar.gz"; then
    echo "ERROR: CodeQL bundle 下载失败（${url}）。" >&2
    return 1
  fi
  tar -xzf "${dest}/codeql-bundle.tar.gz" -C "$dest" || {
    echo "ERROR: CodeQL bundle 解压失败。" >&2
    return 1
  }
  if _is_codeql_cli "${dest}/codeql/codeql"; then
    printf '%s\n' "${dest}/codeql/codeql"
    return 0
  fi

  echo "ERROR: 兜底安装后仍未找到可执行的 CodeQL CLI。" >&2
  return 1
}

# 主入口：按「已知位置 → 兜底安装」顺序解析，成功时导出 CODEQL_CLI
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
