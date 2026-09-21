#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# GPG 密钥全自动安装脚本（幂等 / 可自愈 / 无人工介入）
#
# 设计目标：一条命令跑完即完成「密钥导入 + 信任 + 签名接管」全链路，
#          任何环境（有/无 TTY、变量有/无、重复执行）都不需要人工干预。
#
# 用法：
#   bash install_gpg_keys.sh
#
# 说明：
#   - 本脚本自包含（仅依赖系统 gnupg / curl / jq，缺失时自动安装），
#     不依赖仓库内其它脚本，任何环境可直接运行。
#   - CNB 平台默认已提供签名器 cnb-gpgsign；本脚本用于需要「触发者本人 GPG
#     密钥」亲自签名的场景（保证签名主体落在本人指纹上，而非平台章）。
#
# 环境变量：
#   GPG_API / PLUGIN_GPG_API   密钥分发 API 地址（缺失时回落到内置默认地址）
#   GPG_KEY / PLUGIN_GPG_KEY   私钥解锁短语 passphrase
# ==============================================================================

# 内置默认分发 API（环境变量未注入时的兜底，避免因变量缺失而中断）
DEFAULT_API_URL="https://1329111128-j4hombe7rr.in.ap-guangzhou.tencentscf.com"

# 优先级：PLUGIN_ 前缀（CNB 注入规范）> 无前缀 > 内置默认值
API_URL="${PLUGIN_GPG_API:-${GPG_API:-$DEFAULT_API_URL}}"
GPG_KEY_VALUE="${PLUGIN_GPG_KEY:-${GPG_KEY:-}}"

# 校验：passphrase 必须显式注入，绝不猜测/拼接（私钥为加密存储）
if [ -z "$GPG_KEY_VALUE" ]; then
    echo "❌ 未设置私钥解锁短语环境变量（GPG_KEY / PLUGIN_GPG_KEY）"
    exit 1
fi

# 公网地址可达性重试参数（应对冷启动 / DNS 抖动）
CURL_RETRY_MAX=5
CURL_RETRY_SLEEP=2

log()  { echo "==> $*"; }
ok()   { echo "✅ $*"; }
warn() { echo "⚠️  $*"; }

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
# 3. 从分发 API 获取密钥地址（带重试）
# ------------------------------------------------------------------------------
log "获取密钥分发地址..."
API_RESPONSE="$(retry_run "拉取分发 API" curl -fsSL --connect-timeout 10 --max-time 30 "$API_URL")" || {
    echo "❌ 分发 API 不可达：$API_URL"
    exit 1
}
[ -n "$API_RESPONSE" ] || { echo "❌ API 响应为空"; exit 1; }

PRIVATE_KEY_URL="$(echo "$API_RESPONSE" | jq -r '.private_key_url // empty')"
PUBLIC_KEY_URL="$(echo "$API_RESPONSE"  | jq -r '.public_key_url // empty')"
PLATFORM="$(echo "$API_RESPONSE" | jq -r '.platform // empty' 2>/dev/null || true)"
if [ -z "$PRIVATE_KEY_URL" ] || [ "$PRIVATE_KEY_URL" = "null" ]; then
    echo "❌ 无法从 API 响应解析 private_key_url"
    exit 1
fi
log "平台标识：${PLATFORM:-未知}"

# ------------------------------------------------------------------------------
# 4. 下载公私钥到安全临时目录（自动清理，无论成功失败）
# ------------------------------------------------------------------------------
TMP_DIR="$(mktemp -d)"
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT INT TERM

PRIVATE_KEY_FILE="$TMP_DIR/private_key.asc"
PUBLIC_KEY_FILE="$TMP_DIR/public_key.asc"

log "下载密钥..."
retry_run "下载私钥" curl -fsSL --connect-timeout 10 --max-time 60 -o "$PRIVATE_KEY_FILE" "$PRIVATE_KEY_URL"
[ -s "$PRIVATE_KEY_FILE" ] || { echo "❌ 私钥文件为空"; exit 1; }
grep -q 'BEGIN PGP PRIVATE KEY' "$PRIVATE_KEY_FILE" || { echo "❌ 私钥文件格式非法（非 PGP PRIVATE KEY）"; exit 1; }

if [ -n "$PUBLIC_KEY_URL" ] && [ "$PUBLIC_KEY_URL" != "null" ]; then
    retry_run "下载公钥" curl -fsSL --connect-timeout 10 --max-time 60 -o "$PUBLIC_KEY_FILE" "$PUBLIC_KEY_URL" || warn "公钥下载失败（不影响私钥导入）"
fi

# ------------------------------------------------------------------------------
# 5. 导入密钥（--passphrase 解锁加密私钥；幂等：重复导入不会报错）
# ------------------------------------------------------------------------------
log "导入密钥..."
gpg --batch --yes --no-tty --pinentry-mode loopback --passphrase "$GPG_KEY_VALUE" \
    --import "$PRIVATE_KEY_FILE"
if [ -s "$PUBLIC_KEY_FILE" ]; then
    gpg --batch --yes --no-tty --import "$PUBLIC_KEY_FILE" || true
fi

# ------------------------------------------------------------------------------
# 6. 提取本次导入私钥的精确指纹集合（主密钥 + 各子密钥），供选键与验签比对
# ------------------------------------------------------------------------------
FINGERPRINTS="$(extract_private_key_fingerprints "$PRIVATE_KEY_FILE" "$GPG_KEY_VALUE" || true)"
KEY_ID="$(echo "$FINGERPRINTS" | awk '{print $1}')"
if [ -z "$KEY_ID" ]; then
    # 退化：直接从主密钥环取主密钥指纹
    KEY_ID="$(gpg --list-secret-keys --with-colons 2>/dev/null | awk -F: '/^sec:/{print $5; exit}')"
fi
if [ -z "$KEY_ID" ]; then
    echo "❌ 导入后未在密钥环中找到私钥（sec）"
    exit 1
fi
log "私钥指纹：${KEY_ID}（完整集合：${FINGERPRINTS:-$KEY_ID}）"

# ------------------------------------------------------------------------------
# 7. 设置终极信任（关键修复：全程无 TTY，用 --with-colons 判定结果）
#    旧实现依赖 `echo -e "trust\n5\ny\nquit" | --command-fd 0`，
#    在无 TTY 环境下会挂起并把退出码置为 2 —— 这里改为完全不依赖交互。
# ------------------------------------------------------------------------------
log "设置密钥 ${KEY_ID} 为终极信任..."
printf 'trust\n5\ny\nsave\n' | gpg --batch --no-tty --command-fd 0 --status-fd 1 \
    --pinentry-mode loopback --passphrase "$GPG_KEY_VALUE" \
    --edit-key "$KEY_ID" >/dev/null 2>&1 || true
# 兜底：直接以 ownertrust 导入（对 CNB 打章判定足够）
echo "${KEY_ID}:6:" | gpg --import-ownertrust >/dev/null 2>&1 || true
gpg --check-trustdb >/dev/null 2>&1 || true

# ------------------------------------------------------------------------------
# 8. 生成 GPG 包装脚本（无 TTY 环境签名的关键：统一带 passphrase + loopback）
# ------------------------------------------------------------------------------
WRAPPER="/tmp/gpg-wrapper.sh"
cat > "$WRAPPER" <<EOF
#!/usr/bin/env bash
# 自动生成：无 TTY 下统一走 loopback 并用 passphrase 解锁签名
exec gpg --batch --no-tty --pinentry-mode loopback --passphrase "$GPG_KEY_VALUE" "\$@"
EOF
chmod 700 "$WRAPPER"

# ------------------------------------------------------------------------------
# 9. 配置 Git 全局签名（幂等）
# ------------------------------------------------------------------------------
git config --global user.signingkey "$KEY_ID"
git config --global commit.gpgsign true
git config --global tag.gpgsign true
git config --global gpg.program "$WRAPPER"
# 回填身份，避免平台校验 403 "Author is invalid"
[ -n "${CNB_BUILD_USER_NICKNAME:-}" ] && git config --global user.name "$CNB_BUILD_USER_NICKNAME"
[ -n "${CNB_BUILD_USER_EMAIL:-}" ] && git config --global user.email "$CNB_BUILD_USER_EMAIL"

# ------------------------------------------------------------------------------
# 10. 持久化 GPG_TTY（无 TTY 时写入 /dev/tty 亦可，签名实际走 wrapper）
# ------------------------------------------------------------------------------
CURRENT_TTY="$(tty 2>/dev/null || true)"
case "$CURRENT_TTY" in
    ""|"not a tty") CURRENT_TTY="/dev/tty" ;;
esac
grep -qxF "export GPG_TTY=\"$CURRENT_TTY\"" ~/.bashrc 2>/dev/null \
    || echo "export GPG_TTY=\"$CURRENT_TTY\"" >>~/.bashrc
export GPG_TTY="$CURRENT_TTY"

# ------------------------------------------------------------------------------
# 11. 闭环自检：真实 git commit -S + 验签，失败即报错（不假装成功）
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
ok "GPG 已全自动就绪：指纹=${KEY_ID}，wrapper=${WRAPPER}"
