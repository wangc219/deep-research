#!/bin/bash

# Deep Research 一体化系统初始化脚本（Bash/Linux/macOS）

set -e
TASK_CALLER_DIR="$PWD"
TASK_INIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TASK_ENV_FILE="${DEEP_RESEARCH_ENV_FILE:-.env}"
if [[ "$TASK_ENV_FILE" != /* ]]; then
    if [[ "${1:-}" == "--validate-security-env" && -f "$TASK_CALLER_DIR/$TASK_ENV_FILE" ]]; then
        TASK_ENV_FILE="$TASK_CALLER_DIR/$TASK_ENV_FILE"
    else
        TASK_ENV_FILE="$TASK_INIT_ROOT/$TASK_ENV_FILE"
    fi
fi
cd "$TASK_INIT_ROOT"
umask 077

generate_hex() {
    local length="$1"
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex "$length"
    else
        tr -dc 'a-f0-9' < /dev/urandom | head -c $((length * 2))
    fi
}

set_env_value() {
    local name="$1"
    local value="$2"

    if grep -Eq "^${name}=" "$TASK_ENV_FILE"; then
        ENV_VALUE="$value" awk -v name="$name" '
            $0 ~ "^" name "=" {
                if (!updated) {
                    print name "=" ENVIRON["ENV_VALUE"]
                    updated = 1
                }
                next
            }
            { print }
        ' "$TASK_ENV_FILE" > "${TASK_ENV_FILE}.tmp"
        mv "${TASK_ENV_FILE}.tmp" "$TASK_ENV_FILE"
    else
        printf '\n%s=%s\n' "$name" "$value" >> "$TASK_ENV_FILE"
    fi
}

get_env_value() {
    local name="$1"
    awk -v name="$name" '
        index($0, name "=") == 1 && !found {
            print substr($0, length(name) + 2)
            found = 1
        }
    ' "$TASK_ENV_FILE"
}

trim_whitespace() {
    local value="$1"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    printf '%s' "$value"
}

security_secret_is_valid() {
    local value="$1"
    shift
    local trimmed
    trimmed=$(trim_whitespace "$value")
    if [ "$value" != "$trimmed" ] || [ "${#value}" -lt 32 ]; then
        return 1
    fi
    case "$value" in
        \"*|*\"|\'*|*\') return 1 ;;
    esac
    local other
    for other in "$@"; do
        if [ -n "$other" ] && [ "$value" = "$other" ]; then
            return 1
        fi
    done
}

read_security_secret() {
    local name="$1"
    shift
    local value
    while true; do
        read -s -p "Please enter your ${name} (press Enter to auto-generate): " value
        echo ""
        if [ -z "$value" ]; then
            value=$(generate_hex 32)
            echo "Generated ${name} and saved it to .env."
        fi
        if security_secret_is_valid "$value" "$@"; then
            SECURITY_SECRET_VALUE="$value"
            return
        fi
        echo "❌ ${name} must contain at least 32 non-whitespace characters and must not reuse another security secret."
    done
}

ensure_security_secret() {
    local name="$1"
    shift
    local current
    current=$(get_env_value "$name")
    local other_values=()
    local other_name
    for other_name in "$@"; do
        other_values+=("$(get_env_value "$other_name")")
    done
    if security_secret_is_valid "$current" "${other_values[@]}"; then
        return
    fi

    echo "${name} is missing, too short, or reuses another security secret in .env."
    read_security_secret "$name" "${other_values[@]}"
    set_env_value "$name" "$SECURITY_SECRET_VALUE"
}

validate_security_env() {
    local jwt_secret api_key_secret sandbox_secret
    jwt_secret=$(get_env_value "JWT_SECRET_KEY")
    api_key_secret=$(get_env_value "API_KEY_DERIVATION_SECRET")
    sandbox_secret=$(get_env_value "SANDBOX_PROVISIONER_TOKEN")

    security_secret_is_valid "$jwt_secret" || {
        echo "JWT_SECRET_KEY must contain at least 32 non-whitespace characters." >&2
        return 1
    }
    security_secret_is_valid "$api_key_secret" "$jwt_secret" || {
        echo "API_KEY_DERIVATION_SECRET must be at least 32 characters and independent from JWT_SECRET_KEY." >&2
        return 1
    }
    security_secret_is_valid "$sandbox_secret" "$jwt_secret" "$api_key_secret" || {
        echo "SANDBOX_PROVISIONER_TOKEN must be at least 32 characters and independent from other security secrets." >&2
        return 1
    }
}

ensure_jwt_env() {
    ensure_security_secret "JWT_SECRET_KEY"
    ensure_security_secret "API_KEY_DERIVATION_SECRET" "JWT_SECRET_KEY"

    if ! grep -Eq '^DEEP_RESEARCH_INSTANCE_ID=.+' "$TASK_ENV_FILE"; then
        echo "系统实例标识缺失。"
        read -p "请输入系统实例标识（回车自动生成）: " DEEP_RESEARCH_INSTANCE_ID
        if [ -z "$DEEP_RESEARCH_INSTANCE_ID" ]; then
            DEEP_RESEARCH_INSTANCE_ID="instance-$(generate_hex 8)"
            echo "已自动生成系统实例标识并保存到 .env。"
        fi

        set_env_value "DEEP_RESEARCH_INSTANCE_ID" "$DEEP_RESEARCH_INSTANCE_ID"
    fi
}

ensure_sandbox_env() {
    ensure_security_secret "SANDBOX_PROVISIONER_TOKEN" "JWT_SECRET_KEY" "API_KEY_DERIVATION_SECRET"
}

bash scripts/migrate-environment.sh "$TASK_ENV_FILE"

if [ "${1:-}" = "--validate-security-env" ]; then
    if [ ! -f "$TASK_ENV_FILE" ]; then
        echo "$TASK_ENV_FILE does not exist" >&2
        exit 1
    fi
    validate_security_env
    exit 0
fi

skip_existing_image() {
    local image="$1"

    if ! docker image inspect "$image" >/dev/null 2>&1; then
        return 1
    fi

    echo "⏭️  ${image} already exists. Skipping pull."
    return 0
}

echo "🚀 正在初始化 Deep Research 一体化系统..."
echo "=================================="

# Check if .env file exists
if [ -f "$TASK_ENV_FILE" ]; then
    echo "✅ 已发现 .env，正在检查必需配置。"
    ensure_jwt_env
    ensure_sandbox_env
    validate_security_env
    chmod 600 "$TASK_ENV_FILE"
else
    echo "📝 未发现 .env，现在创建系统配置。"
    echo ""

    echo "模型供应商与 API Key 在启动后的 /models 页面配置，无需在初始化时填写。"

    # open-websearch is deployed by Compose and needs no API key. Paid and
    # direct-public providers remain explicit alternatives.
    echo ""
    echo "🔍 Web Search Provider (open-websearch multi-engine search is enabled by default)"
    echo "0) open-websearch (no API Key, default)"
    echo "1) public (direct HTML search fallback)"
    echo "2) doubao (Doubao Custom Search)"
    echo "3) tavily (Tavily Search)"
    read -p "Select provider (0/open-websearch, 1/public, 2/doubao, 3/tavily, Enter for default): " SEARCH_CHOICE

    WEB_SEARCH_PROVIDER="open-websearch"
    DOUBAO_SEARCH_API_KEY=""
    TAVILY_API_KEY=""

    if [ "$SEARCH_CHOICE" = "1" ] || [ "$SEARCH_CHOICE" = "public" ]; then
        WEB_SEARCH_PROVIDER="public"
    elif [ "$SEARCH_CHOICE" = "2" ] || [ "$SEARCH_CHOICE" = "doubao" ]; then
        WEB_SEARCH_PROVIDER="doubao"
        echo "Get your Doubao API Key from Volcengine Console https://console.volcengine.com/search-infinity/api-key"
        read -s -p "Please enter your DOUBAO_SEARCH_API_KEY: " DOUBAO_SEARCH_API_KEY
        echo ""
    elif [ "$SEARCH_CHOICE" = "3" ] || [ "$SEARCH_CHOICE" = "tavily" ]; then
        WEB_SEARCH_PROVIDER="tavily"
        echo "Get your Tavily API key from: https://app.tavily.com/"
        read -s -p "Please enter your TAVILY_API_KEY: " TAVILY_API_KEY
        echo ""
    fi

    echo ""
    echo "JWT security settings"
    read_security_secret "JWT_SECRET_KEY"
    JWT_SECRET_KEY="$SECURITY_SECRET_VALUE"

    read_security_secret "API_KEY_DERIVATION_SECRET" "$JWT_SECRET_KEY"
    API_KEY_DERIVATION_SECRET="$SECURITY_SECRET_VALUE"

    read -p "请输入系统实例标识（回车自动生成）: " DEEP_RESEARCH_INSTANCE_ID
    if [ -z "$DEEP_RESEARCH_INSTANCE_ID" ]; then
        DEEP_RESEARCH_INSTANCE_ID="instance-$(generate_hex 8)"
        echo "已自动生成系统实例标识并保存到 .env。"
    fi

    read_security_secret "SANDBOX_PROVISIONER_TOKEN" "$JWT_SECRET_KEY" "$API_KEY_DERIVATION_SECRET"
    SANDBOX_PROVISIONER_TOKEN="$SECURITY_SECRET_VALUE"

    # Create .env file
    cat > "$TASK_ENV_FILE" << EOF
# 模型与 API Key 统一在 /models 配置；此文件只保存基础设施配置。

# Web Search Provider settings
EOF

    if [ -n "$WEB_SEARCH_PROVIDER" ]; then
        echo "WEB_SEARCH_PROVIDER=${WEB_SEARCH_PROVIDER}" >> "$TASK_ENV_FILE"
    fi
    if [ "$WEB_SEARCH_PROVIDER" = "open-websearch" ]; then
        echo "OPEN_WEBSEARCH_URL=http://open-websearch:3210" >> "$TASK_ENV_FILE"
        echo "OPEN_WEBSEARCH_ENGINES=bing,duckduckgo" >> "$TASK_ENV_FILE"
    fi
    if [ -n "$DOUBAO_SEARCH_API_KEY" ]; then
        echo "DOUBAO_SEARCH_API_KEY=${DOUBAO_SEARCH_API_KEY}" >> "$TASK_ENV_FILE"
    fi
    if [ -n "$TAVILY_API_KEY" ]; then
        echo "TAVILY_API_KEY=${TAVILY_API_KEY}" >> "$TASK_ENV_FILE"
    fi

    cat >> "$TASK_ENV_FILE" << EOF

# JWT security settings
JWT_SECRET_KEY=${JWT_SECRET_KEY}
API_KEY_DERIVATION_SECRET=${API_KEY_DERIVATION_SECRET}
DEEP_RESEARCH_INSTANCE_ID=${DEEP_RESEARCH_INSTANCE_ID}
SANDBOX_PROVISIONER_TOKEN=${SANDBOX_PROVISIONER_TOKEN}
EOF

    validate_security_env
    chmod 600 "$TASK_ENV_FILE"
    echo "✅ .env file created successfully!"
fi

echo ""
echo "📦 Pulling Docker images..."
echo "========================="

# List of Docker images to pull
images=(
    "python:3.13-slim"
    "node:24-slim"
    "node:24-alpine"
    "milvusdb/milvus:v2.5.6"
    "neo4j:5.26.29"
    "quay.io/minio/minio:RELEASE.2023-03-20T20-16-18Z"
    "ghcr.io/astral-sh/uv:0.12.6"
    "nginx:alpine"
    "quay.io/coreos/etcd:v3.5.5"
    "postgres:16"
    "redis:7.4.10-alpine"
)

# Pull each image
for image in "${images[@]}"; do
    if skip_existing_image "$image"; then
        continue
    fi

    echo "🔄 Pulling ${image}..."
    if bash scripts/pull_image.sh "$image"; then
        echo "✅ Successfully pulled ${image}"
    else
        echo "❌ Failed to pull ${image}"
        exit 1
    fi
done

sandbox_image="enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:1.11.0"
if ! skip_existing_image "$sandbox_image"; then
    echo "🔄 Pulling ${sandbox_image}..."
    docker pull "$sandbox_image"
    echo "✅ Successfully pulled ${sandbox_image}"
fi

echo ""
echo "🎉 Deep Research 初始化完成！"
echo "=========================="
echo "一键构建启动: bash scripts/platform.sh start"
echo "日常直接启动: bash scripts/platform.sh up"
echo "默认使用静态前端和无热重载服务；开发模式使用 PLATFORM_MODE=dev。"
echo "After login, configure chat models in 模型设置 (/models). Equipment research, Query generation, and deep dialogue all use that page — not EQUIPMENT_DR_* in .env."
