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

# Codespaces secrets arrive as environment variables. An empty `KEY=` line in
# the .env file would override one when the file is loaded with
# `set -a && source .env` (an empty value wins), so the backend would start
# without e.g. GROQ_API_KEY. Comment out every empty line whose name the
# environment provides; a value typed into the file is never touched.
# Names only are printed, never values.
#
# Usage: defer_empty_to_environment <file>
defer_empty_to_environment() {
  local file="$1" key
  [ -f "$file" ] || return 0
  while IFS= read -r key; do
    if [ -n "${!key:-}" ]; then
      sed -i.bak "s/^${key}=\$/# ${key}= (set by a Codespaces secret - leave this line commented out)/" "$file" \
        && rm -f "${file}.bak"
      echo "    $key: using the Codespaces secret"
    fi
  done < <(grep -oE '^[A-Za-z_][A-Za-z0-9_]*=$' "$file" | sed 's/=$//')
}
