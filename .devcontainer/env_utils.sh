#!/usr/bin/env bash
# Shared helper for setup.sh/start-services.sh: idempotently set KEY=VALUE
# in a .env-style file, replacing an existing line for that key (however
# it was previously set) instead of appending a duplicate. Plain grep/sed,
# no python dependency, so it works before any venv exists.
#
# Usage: set_env_var <file> <KEY> <VALUE>
set_env_var() {
  local file="$1"
  local key="$2"
  local value="$3"
  touch "$file"
  if grep -q "^${key}=" "$file"; then
    # Escape sed-significant characters in the replacement value.
    local escaped
    escaped=$(printf '%s' "$value" | sed -e 's/[\/&]/\\&/g')
    # -i.bak (then removing the backup) works with both GNU sed (Linux,
    # Codespaces) and BSD sed (macOS), unlike a bare -i.
    sed -i.bak "s/^${key}=.*/${key}=${escaped}/" "$file" && rm -f "${file}.bak"
  else
    printf '%s=%s\n' "$key" "$value" >> "$file"
  fi
}
