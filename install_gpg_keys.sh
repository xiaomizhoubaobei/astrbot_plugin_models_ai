#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# GPG 密钥全自动安装脚本（幂等 / 可自愈 / 无人工介入）
#
# 设计目标：一条命令跑完即完成「密钥导入 + 信任 + 签名接管」全链路，
#          任何环境（有/无 TTY、变量有/无、重复执行）都不需要人工干预。
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
PLATFORM="$(echo "$API_RESPONSE" | jq -r '.platform // "unknown"')"
if [ -z "$PRIVATE_KEY_URL" ] || [ "$PRIVATE_KEY_URL" = "null" ]; then
    echo "❌ 无法从 API 响应解析 private_key_url"
    exit 1
fi
log "平台标识：${PLATFORM}"

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
# 6. 提取主指纹（主密钥 ID）
# ------------------------------------------------------------------------------
KEY_ID="$(gpg --list-secret-keys --with-colons 2>/dev/null | awk -F: '/^sec:/{print $5; exit}')"
if [ -z "$KEY_ID" ]; then
    echo "❌ 导入后未在密钥环中找到私钥（sec）"
    exit 1
fi
log "私钥指纹：${KEY_ID}"

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
# ------------------------------------------------------------------------------
log "执行签名闭环自检..."
VERIFY_DIR="$TMP_DIR/verify"
mkdir -p "$VERIFY_DIR"
# 注意：自检在子 shell 中执行，失败必须显式探测退出码（不能用管道，避免 exit 被吞）
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
    # 必须出现 Good signature，且指纹落在本次导入的密钥上
    grep -q "Good signature" "$SELFCHECK_LOG" || exit 1
    grep -q "$KEY_ID" "$SELFCHECK_LOG" || exit 1
    exit 0
); then
    selfcheck_ok=1
fi

if [ "$selfcheck_ok" -ne 1 ]; then
    echo "❌ 签名闭环自检失败：git commit -S 未产生落在本人密钥（${KEY_ID}）上的 Good signature"
    [ -f "$SELFCHECK_LOG" ] && { echo "----- 自检日志 -----"; cat "$SELFCHECK_LOG"; }
    exit 1
fi

ok "签名闭环自检通过：Good signature（密钥 ${KEY_ID}）"
ok "GPG 已全自动就绪：指纹=${KEY_ID}，wrapper=${WRAPPER}"
