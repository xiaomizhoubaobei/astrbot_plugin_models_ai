#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# GPG 密钥全自动安装脚本（幂等 / 可自愈 / 无人工介入 / 平台可定向）
#
# 设计目标：一条命令跑完即完成「密钥导入 + 信任 + 签名接管 + 闭环自检」全链路，
#          任何环境（有/无 TTY、变量有/无、重复执行）都不需要人工干预。
#
# 用法：
#   bash install_gpg_keys.sh                 # 自动探测可用平台
#   GIT_PLATFORM=gitLab bash install_gpg_keys.sh   # 显式指定平台（推荐）
#
# 说明：
#   - 本脚本自包含（仅依赖系统 gnupg / curl / jq，缺失时自动安装），
#     不依赖仓库内其它脚本，任何环境可直接运行。
#   - CNB 平台默认已提供签名器 cnb-gpgsign；本脚本用于需要「触发者本人 GPG
#     密钥」亲自签名的场景（保证签名主体落在本人指纹上，而非平台章）。
#
# 环境变量：
#   GPG_API / PLUGIN_GPG_API    密钥分发 API 地址（缺失时回落到内置默认地址）
#   GPG_KEY / PLUGIN_GPG_KEY    私钥解锁短语 passphrase（必填）
#   GIT_PLATFORM / PLUGIN_GIT_PLATFORM
#                               目标平台标识（gitee/gitLab/coding/codeup/github/cnb/mobile_only）
#                               未设置时：分布式 API 返回什么就用什么（并做告警）
#   GPG_EXPECT_FINGERPRINT / PLUGIN_GPG_EXPECT_FINGERPRINT
#                               期望的密钥指纹（可选）。设置后若导入密钥指纹不匹配
#                               则直接失败，避免「装错钥」而静默通过。
# ==============================================================================

# 内置默认分发 API（环境变量未注入时的兜底，避免因变量缺失而中断）
DEFAULT_API_URL="https://1329111128-j4hombe7rr.in.ap-guangzhou.tencentscf.com"

# 已知平台白名单（用于校验与 URL 定向；仅这些标识在 COS 上存在对应密钥文件）
KNOWN_PLATFORMS=(gitee gitLab coding codeup github cnb mobile_only)

# 优先级：PLUGIN_ 前缀（CNB 注入规范）> 无前缀 > 内置默认值
API_URL="${PLUGIN_GPG_API:-${GPG_API:-$DEFAULT_API_URL}}"
GPG_KEY_VALUE="${PLUGIN_GPG_KEY:-${GPG_KEY:-}}"
GIT_PLATFORM="${PLUGIN_GIT_PLATFORM:-${GIT_PLATFORM:-}}"
EXPECT_FP="${PLUGIN_GPG_EXPECT_FINGERPRINT:-${GPG_EXPECT_FINGERPRINT:-}}"

# 校验：passphrase 必须显式注入，绝不猜测/拼接（私钥为加密存储）
if [ -z "$GPG_KEY_VALUE" ]; then
    echo "❌ 未设置私钥解锁短语环境变量（GPG_KEY / PLUGIN_GPG_KEY）"
    exit 1
fi

# 公网地址可达性重试参数（应对冷启动 / DNS 抖动）
CURL_RETRY_MAX=5

log()  { echo "==> $*"; }
ok()   { echo "✅ $*"; }
warn() { echo "⚠️  $*"; }
die()  { echo "❌ $*" >&2; exit 1; }

# ------------------------------------------------------------------------------
# 从 `git log --show-signature` 输出中提取实际签名指纹（十六进制）。
# 自包含实现（不依赖仓库内其它脚本）；输出空字符串表示未提取到（裸签/平台章）。
# ------------------------------------------------------------------------------
extract_gpg_fingerprint() {
    grep -oE "using [A-Z0-9]+ key [0-9A-F]{16,40}" \
      | grep -oE "[0-9A-F]{16,40}" \
      | head -1
}

# 判断实际指纹是否命中期望指纹集合（空格分隔多把；忽略大小写与短/长差异）。
# 任一命中即判定接管（git 签名常落在子密钥上，故比对主+子完整集合）。
check_gpg_fingerprint() {
    local actual="$1" expected="$2" cand=""
    [ -n "$actual" ] || return 1
    for cand in $expected; do
        echo "$actual" | grep -qiE "$cand" && return 0
    done
    return 1
}

# 校验平台标识是否在已知白名单内（避免拼错平台名导致 404 或装错钥）。
is_known_platform() {
    local p="$1" k
    for k in "${KNOWN_PLATFORMS[@]}"; do
        [ "$k" = "$p" ] && return 0
    done
    return 1
}

# 从形如 `.../GPG/<platform>_private_key.asc` 的 URL 中提取平台标识。
# 提取失败返回非零（URL 结构非预期即视为异常，宁可失败也不装错钥）。
extract_platform_from_url() {
    local url="$1" name=""
    name="$(echo "$url" | sed -E 's#.*/##; s/_(private|public)_key\.asc$//')"
    [ -n "$name" ] || return 1
    echo "$name"
}

# 在隔离密钥环中导入私钥并提取其主+子指纹（空格分隔，首个为主指纹）。
# 隔离导入可避免误取密钥环中历史遗留密钥，确保指纹属于本次下载的这把。
extract_private_key_fingerprints() {
    local keyfile="$1" passphrase="$2" iso_home="" fps=""
    [ -s "$keyfile" ] || return 1
    iso_home=$(mktemp -d 2>/dev/null) || return 1
    chmod 700 "$iso_home" 2>/dev/null || true
    GNUPGHOME="$iso_home" gpg --batch --yes --pinentry-mode loopback \
        --passphrase "$passphrase" --import "$keyfile" >/dev/null 2>&1
    fps=$(GNUPGHOME="$iso_home" gpg --batch --list-secret-keys \
        --with-colons 2>/dev/null | awk -F: '$1=="fpr"{print substr($10,25)}' | paste -sd' ' -)
    rm -rf "$iso_home"
    [ -n "$fps" ] || return 1
    echo "$fps"
}

# ------------------------------------------------------------------------------
# 带指数退避的重试执行器（仅用于网络类操作）
# ------------------------------------------------------------------------------
retry_run() {
    local desc="$1"; shift
    local attempt=1 delay=1
    while true; do
        if "$@"; then
            return 0
        fi
        if [ "$attempt" -ge "$CURL_RETRY_MAX" ]; then
            echo "❌ ${desc} 重试 ${attempt} 次后仍失败"
            return 1
        fi
        warn "${desc} 第 ${attempt} 次失败，${delay}s 后重试..."
        sleep "$delay"
        attempt=$((attempt + 1))
        delay=$((delay * 2))
    done
}

# ------------------------------------------------------------------------------
# 1. 安装必要工具（幂等：逐个探测，缺哪个装哪个）
# ------------------------------------------------------------------------------
APT_PKGS=()
command -v gpg  >/dev/null 2>&1 || APT_PKGS+=("gnupg")
command -v curl >/dev/null 2>&1 || APT_PKGS+=("curl")
command -v jq   >/dev/null 2>&1 || APT_PKGS+=("jq")
if [ "${#APT_PKGS[@]}" -gt 0 ]; then
    log "安装缺失依赖：${APT_PKGS[*]}"
    SUDO=""
    [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1 && SUDO="sudo"
    $SUDO apt-get update -qq
    DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y --no-install-recommends "${APT_PKGS[@]}"
fi

# ------------------------------------------------------------------------------
# 2. 准备 GNUPGHOME 与无 TTY 环境配置（关键：容器内必须走 loopback）
# ------------------------------------------------------------------------------
export GNUPGHOME="${GNUPGHOME:-$HOME/.gnupg}"
mkdir -p "$GNUPGHOME"
chmod 700 "$GNUPGHOME"

# 写入 pinentry loopback 配置，保证无 TTY 环境也能自动解锁私钥
touch "$GNUPGHOME/gpg.conf" "$GNUPGHOME/gpg-agent.conf"
grep -qxF 'pinentry-mode loopback' "$GNUPGHOME/gpg.conf" || echo 'pinentry-mode loopback' >>"$GNUPGHOME/gpg.conf"
grep -qxF 'allow-loopback-pinentry' "$GNUPGHOME/gpg-agent.conf" || echo 'allow-loopback-pinentry' >>"$GNUPGHOME/gpg-agent.conf"
grep -qxF 'no-tty' "$GNUPGHOME/gpg.conf" || echo 'no-tty' >>"$GNUPGHOME/gpg.conf"

# 重启 gpg-agent 使配置生效（幂等）
gpgconf --kill gpg-agent >/dev/null 2>&1 || true
gpgconf --launch gpg-agent >/dev/null 2>&1 || true

# ------------------------------------------------------------------------------
# 3. 从分发 API 获取密钥地址
#    注意：该 API 的 ?key= 参数实测被忽略（同一 key 会随机返回不同平台），
#    因此这里只把它当作「获取密钥基址」的手段，平台定向由第 4 步客户端改写完成。
# ------------------------------------------------------------------------------
log "获取密钥分发地址..."
API_RESPONSE="$(retry_run "拉取分发 API" curl -fsSL --connect-timeout 10 --max-time 30 "$API_URL")" || {
    echo "❌ 分发 API 不可达：$API_URL"
    exit 1
}
[ -n "$API_RESPONSE" ] || die "API 响应为空"

API_PLATFORM="$(echo "$API_RESPONSE" | jq -r '.platform // empty' 2>/dev/null || true)"
PRIVATE_KEY_URL="$(echo "$API_RESPONSE" | jq -r '.private_key_url // empty')"
PUBLIC_KEY_URL="$(echo "$API_RESPONSE"  | jq -r '.public_key_url // empty')"

# 兜底：如果 JSON 解析失败，容错从 URL 片段推导（保证结构可推导）
if [ -z "$PRIVATE_KEY_URL" ] || [ "$PRIVATE_KEY_URL" = "null" ]; then
    die "无法从 API 响应解析 private_key_url（响应：$(echo "$API_RESPONSE" | head -c 200)）"
fi

# ------------------------------------------------------------------------------
# 4. 平台定向：把 API 返回的 URL 改写成目标平台
#    - GIT_PLATFORM 显式指定 -> 改写并校验
#    - 未指定 -> 采用 API 返回平台，且校验其在白名单内
# ------------------------------------------------------------------------------
API_PLATFORM_FROM_URL="$(extract_platform_from_url "$PRIVATE_KEY_URL" || true)"
log "API 返回平台：${API_PLATFORM:-未知}（URL 推导：${API_PLATFORM_FROM_URL:-未知}）"

if [ -n "$GIT_PLATFORM" ]; then
    is_known_platform "$GIT_PLATFORM" || die "不支持的平台标识：$GIT_PLATFORM（可选：${KNOWN_PLATFORMS[*]}）"
    BASE_URI="$(echo "$PRIVATE_KEY_URL" | sed -E 's#/[^/]*$##')"
    PRIVATE_KEY_URL="${BASE_URI}/${GIT_PLATFORM}_private_key.asc"
    PUBLIC_KEY_URL="${BASE_URI}/${GIT_PLATFORM}_public_key.asc"
    ok "平台已定向：${GIT_PLATFORM}"
else
    if ! is_known_platform "${API_PLATFORM_FROM_URL:-}"; then
        warn "无法确定平台（推导值：${API_PLATFORM_FROM_URL:-空}）。分发 API 的 ?key= 参数不可靠，"
        warn "建议显式设置 GIT_PLATFORM=<平台>。将按 API 返回 URL 继续尝试。"
    else
        warn "未显式指定 GIT_PLATFORM，采用 API 随机返回的平台：${API_PLATFORM_FROM_URL}"
        warn "如需确定性结果，请设置 GIT_PLATFORM=<平台>。"
    fi
fi

# ------------------------------------------------------------------------------
# 5. 下载公私钥到安全临时目录（自动清理，无论成功失败）
# ------------------------------------------------------------------------------
TMP_DIR="$(mktemp -d)"
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT INT TERM

PRIVATE_KEY_FILE="$TMP_DIR/private_key.asc"
PUBLIC_KEY_FILE="$TMP_DIR/public_key.asc"

log "下载密钥..."
retry_run "下载私钥" curl -fsSL --connect-timeout 10 --max-time 60 -o "$PRIVATE_KEY_FILE" "$PRIVATE_KEY_URL"
[ -s "$PRIVATE_KEY_FILE" ] || die "私钥文件为空"
grep -q 'BEGIN PGP PRIVATE KEY' "$PRIVATE_KEY_FILE" || die "私钥文件格式非法（非 PGP PRIVATE KEY）"

if [ -n "$PUBLIC_KEY_URL" ] && [ "$PUBLIC_KEY_URL" != "null" ]; then
    retry_run "下载公钥" curl -fsSL --connect-timeout 10 --max-time 60 -o "$PUBLIC_KEY_FILE" "$PUBLIC_KEY_URL" \
        || warn "公钥下载失败（不影响私钥导入）"
fi

# ------------------------------------------------------------------------------
# 6. 导入密钥（--passphrase 解锁加密私钥；幂等：重复导入不会报错）
# ------------------------------------------------------------------------------
log "导入密钥..."
gpg --batch --yes --no-tty --pinentry-mode loopback --passphrase "$GPG_KEY_VALUE" \
    --import "$PRIVATE_KEY_FILE"
if [ -s "$PUBLIC_KEY_FILE" ]; then
    gpg --batch --yes --no-tty --import "$PUBLIC_KEY_FILE" || true
fi

# ------------------------------------------------------------------------------
# 7. 提取本次导入私钥的精确指纹集合（主密钥 + 各子密钥），供选键与验签比对
# ------------------------------------------------------------------------------
FINGERPRINTS="$(extract_private_key_fingerprints "$PRIVATE_KEY_FILE" "$GPG_KEY_VALUE" || true)"
KEY_ID="$(echo "$FINGERPRINTS" | awk '{print $1}')"
if [ -z "$KEY_ID" ]; then
    # 退化：直接从主密钥环取主密钥指纹
    KEY_ID="$(gpg --list-secret-keys --with-colons 2>/dev/null | awk -F: '/^sec:/{print $5; exit}')"
fi
if [ -z "$KEY_ID" ]; then
    die "导入后未在密钥环中找到私钥（sec）"
fi
log "私钥指纹：${KEY_ID}（完整集合：${FINGERPRINTS:-$KEY_ID}）"

# 期望指纹校验（可选）：设置后指纹不符即失败，杜绝装错钥静默通过。
if [ -n "$EXPECT_FP" ]; then
    if check_gpg_fingerprint "$KEY_ID" "$EXPECT_FP" || check_gpg_fingerprint "$FINGERPRINTS" "$EXPECT_FP"; then
        ok "指纹校验通过：命中期望 ${EXPECT_FP}"
    else
        die "指纹不匹配：实际 ${KEY_ID}，期望 ${EXPECT_FP}（可能装错了平台的密钥）"
    fi
fi

# ------------------------------------------------------------------------------
# 8. 设置终极信任（全程无 TTY，用 --with-colons 判定结果）
#    完全不依赖交互式 trust 编辑器，保证无 TTY 下不挂起。
# ------------------------------------------------------------------------------
log "设置密钥 ${KEY_ID} 为终极信任..."
printf 'trust\n5\ny\nsave\n' | gpg --batch --no-tty --command-fd 0 --status-fd 1 \
    --pinentry-mode loopback --passphrase "$GPG_KEY_VALUE" \
    --edit-key "$KEY_ID" >/dev/null 2>&1 || true
# 兜底：直接以 ownertrust 导入（对 CNB 打章判定足够）
echo "${KEY_ID}:6:" | gpg --import-ownertrust >/dev/null 2>&1 || true
gpg --check-trustdb >/dev/null 2>&1 || true

# ------------------------------------------------------------------------------
# 9. 生成 GPG 包装脚本（无 TTY 环境签名的关键：统一带 passphrase + loopback）
#    避免把 passphrase 写进全局 git config 的明文命令历史；文件权限收紧到 700。
# ------------------------------------------------------------------------------
WRAPPER="$GNUPGHOME/gpg-wrapper.sh"
cat > "$WRAPPER" <<EOF
#!/usr/bin/env bash
# 自动生成：无 TTY 下统一走 loopback 并用 passphrase 解锁签名
exec gpg --batch --no-tty --pinentry-mode loopback --passphrase "$GPG_KEY_VALUE" "\$@"
EOF
chmod 700 "$WRAPPER"

# ------------------------------------------------------------------------------
# 10. 配置 Git 签名：仓库级优先（落盘可见），无仓库时回落到全局
#     关键修复：旧实现只写 --global，若运行目录非 Git 仓库/或仓库级配置已存在，
#     容器内提交时可能不生效。这里按「仓库级 > 全局」双写，确保必然接管。
# ------------------------------------------------------------------------------
configure_git_signing() {
    local scope="$1"; shift
    git config "$scope" user.signingkey "$KEY_ID"
    git config "$scope" commit.gpgsign true
    git config "$scope" tag.gpgsign true
    git config "$scope" gpg.program "$WRAPPER"
    git config "$scope" gpg.format openpgp
}
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    log "检测到 Git 仓库，使用仓库级签名配置（优先级高于全局）"
    configure_git_signing --local
    configure_git_signing --global
else
    log "非 Git 仓库目录，使用全局签名配置"
    configure_git_signing --global
fi
# 回填身份，避免平台校验 403 "Author is invalid"
[ -n "${CNB_BUILD_USER_NICKNAME:-}" ] && git config --global user.name "$CNB_BUILD_USER_NICKNAME"
[ -n "${CNB_BUILD_USER_EMAIL:-}" ] && git config --global user.email "$CNB_BUILD_USER_EMAIL"

# ------------------------------------------------------------------------------
# 11. 持久化 GPG_TTY（无 TTY 时写入 /dev/tty 亦可，签名实际走 wrapper）
# ------------------------------------------------------------------------------
CURRENT_TTY="$(tty 2>/dev/null || true)"
case "$CURRENT_TTY" in
    ""|"not a tty") CURRENT_TTY="/dev/tty" ;;
esac
grep -qxF "export GPG_TTY=\"$CURRENT_TTY\"" ~/.bashrc 2>/dev/null \
    || echo "export GPG_TTY=\"$CURRENT_TTY\"" >>~/.bashrc
export GPG_TTY="$CURRENT_TTY"

# ------------------------------------------------------------------------------
# 12. 闭环自检：真实 git commit -S + 验签，失败即报错（不假装成功）
#     比对主+子完整指纹集合，避免主/子指纹不同导致误报。
# ------------------------------------------------------------------------------
log "执行签名闭环自检..."
VERIFY_DIR="$TMP_DIR/verify"
mkdir -p "$VERIFY_DIR"
SELFCHECK_LOG="$TMP_DIR/selfcheck.log"
selfcheck_ok=0
if (
    cd "$VERIFY_DIR" || exit 1
    git init -q . || exit 1
    git config user.name  "$(git config --global user.name  || echo "$KEY_ID")"
    git config user.email "$(git config --global user.email || echo "${KEY_ID}@localhost")"
    echo "hello GPG" > selfcheck.txt
    git add selfcheck.txt
    git commit -q -S -m "chore(gpg): 签名环境自检" || exit 1
    git log --show-signature -1 >"$SELFCHECK_LOG" 2>&1
    # 必须出现 Good signature，且指纹落在本次导入的密钥（主+子）上
    grep -q "Good signature" "$SELFCHECK_LOG" || exit 1
    sig_fp="$(extract_gpg_fingerprint <"$SELFCHECK_LOG" || true)"
    check_gpg_fingerprint "$sig_fp" "${FINGERPRINTS:-$KEY_ID}" || exit 1
    exit 0
); then
    selfcheck_ok=1
fi

if [ "$selfcheck_ok" -ne 1 ]; then
    echo "❌ 签名闭环自检失败：git commit -S 未产生落在本人密钥（${FINGERPRINTS:-$KEY_ID}）上的 Good signature"
    [ -f "$SELFCHECK_LOG" ] && { echo "----- 自检日志 -----"; cat "$SELFCHECK_LOG"; }
    exit 1
fi

ok "签名闭环自检通过：Good signature（密钥 ${KEY_ID}）"
ok "GPG 已全自动就绪：指纹=${KEY_ID}，平台=${GIT_PLATFORM:-${API_PLATFORM_FROM_URL:-未知}}，wrapper=${WRAPPER}"
