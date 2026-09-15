#!/bin/sh
set -eu

cd "$(dirname "$0")"

has_config=false
for arg in "$@"; do
    case "$arg" in
        --config | --config=*) has_config=true ;;
    esac
done
if [ "$has_config" = false ]; then
    config_file=configs.macos.ini
    if [ -f configs.local.ini ]; then
        config_file=configs.local.ini
        chmod 600 "$config_file"
    fi
    set -- --config "$config_file" "$@"
fi

exec uv run python -u Autovisor.py "$@"
