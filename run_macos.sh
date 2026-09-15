#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

STAMP_DIR=".autovisor"
STAMP_FILE="$STAMP_DIR/env.ready"

# 读取 ini 配置项（跳过注释行）
ini_value() {
    local file="$1" key="$2" target
    target=$(printf '%s' "$key" | tr '[:upper:]' '[:lower:]')
    awk -v target="$target" '
        BEGIN { FS = "=" }
        /^[[:space:]]*[;#]/ { next }
        {
            name = $1
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", name)
            if (tolower(name) == target) {
                value = $2
                for (i = 3; i <= NF; i++) value = value "=" $i
                gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
                print value
                exit
            }
        }
    ' "$file"
}

# 解析参数：识别 --config 与自身开关 --setup(不转发给程序)
force_setup=false
has_config=false
config_file=""
forward=()
args=("$@")
idx=0
while [ "$idx" -lt "${#args[@]}" ]; do
    cur="${args[$idx]}"
    case "$cur" in
        --setup)
            force_setup=true
            ;;
        --config=*)
            has_config=true
            config_file="${cur#--config=}"
            forward+=("$cur")
            ;;
        --config)
            has_config=true
            config_file="${args[$((idx + 1))]:-}"
            forward+=("$cur")
            if [ "$((idx + 1))" -lt "${#args[@]}" ]; then
                forward+=("${args[$((idx + 1))]}")
                idx=$((idx + 1))
            fi
            ;;
        *)
            forward+=("$cur")
            ;;
    esac
    idx=$((idx + 1))
done
if [ -z "$config_file" ]; then
    config_file=config.macos.ini
fi
if [ "$has_config" = true ]; then
    set -- ${forward[@]+"${forward[@]}"}
else
    set -- --config "$config_file" ${forward[@]+"${forward[@]}"}
fi

# 确保 uv 可用
ensure_uv() {
    if command -v uv >/dev/null 2>&1; then
        echo "[setup] 使用已安装的 uv: $(command -v uv)"
        return 0
    fi
    echo "[setup] 未检测到 uv, 正在自动安装..."
    if command -v brew >/dev/null 2>&1; then
        echo "[setup] 通过 Homebrew 安装 uv..."
        brew install uv
        return 0
    fi
    echo "[setup] 使用官方脚本安装 uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh || {
        echo "[ERROR] uv 安装失败, 请手动安装后重试: brew install uv" >&2
        exit 1
    }
    if [ -x "$HOME/.local/bin/uv" ]; then
        export PATH="$HOME/.local/bin:$PATH"
    elif [ -x "$HOME/.cargo/bin/uv" ]; then
        export PATH="$HOME/.cargo/bin:$PATH"
    fi
    command -v uv >/dev/null 2>&1 || {
        echo "[ERROR] 未能找到 uv 可执行文件, 请手动安装后重试: brew install uv" >&2
        exit 1
    }
}

# 首次部署：根据配置安装依赖与浏览器
deploy() {
    local cfg="$1"
    if [ ! -f "$cfg" ]; then
        echo "[ERROR] 未找到配置文件: $cfg" >&2
        echo "[ERROR] 请先复制模板并编辑: cp config.macos.ini.example config.macos.ini" >&2
        exit 1
    fi
    chmod 600 "$cfg"

    ensure_uv

    local captcha driver extra=""
    captcha=$(ini_value "$cfg" enableAutoCaptcha | tr '[:upper:]' '[:lower:]')
    driver=$(ini_value "$cfg" driver | tr '[:upper:]' '[:lower:]')
    case "$captcha" in
        true|1|yes|on) extra="--extra captcha" ;;
    esac
    echo "[setup] 安装 Python 依赖 (uv sync $extra)..."
    uv sync $extra

    case "$driver" in
        chromium)
            echo "[setup] 检测到 driver = chromium, 安装 Playwright Chromium..."
            uv run playwright install chromium
            ;;
        *)
            echo "[setup] 使用系统浏览器(默认 Chrome), 无需下载 Playwright 浏览器。"
            ;;
    esac
}

# 环境指纹: pyproject + lock + 配置 任一变化时重新部署
signature() {
    {
        if [ -f pyproject.toml ]; then
            shasum -a 256 pyproject.toml uv.lock 2>/dev/null | awk '{print $1}'
        fi
        if [ -f "$config_file" ]; then
            shasum -a 256 "$config_file" 2>/dev/null | awk '{print $1}'
        fi
    } | shasum -a 256 | awk '{print $1}'
}

if [ "$force_setup" = true ]; then
    echo "===== Autovisor 强制环境部署 ====="
    deploy "$config_file"
elif [ -f "$STAMP_FILE" ] && [ "$(cat "$STAMP_FILE")" = "$(signature)" ]; then
    echo "[run] 环境已就绪, 直接启动."
else
    echo "===== Autovisor 首次/变更环境部署 ====="
    deploy "$config_file"
    mkdir -p "$STAMP_DIR"
    chmod 700 "$STAMP_DIR"
    printf '%s' "$(signature)" > "$STAMP_FILE"
fi

exec uv run python -u Autovisor.py "$@"