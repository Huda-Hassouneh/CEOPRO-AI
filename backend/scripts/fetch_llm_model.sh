#!/usr/bin/env bash
# Downloads Qwen3-4B-Instruct-2507 (Qwen; licence Apache-2.0, read from the
# file's own GGUF metadata) as a 4-bit GGUF (2.5 GB) for the local language
# model that writes campaign copy and answers the assistant when Groq can't
# (LLM_PROVIDERS=groq,local). Free, no account: Docker Hub's official model
# catalog (docker.io/ai/qwen3), checked against the registry's sha256 digest.
#
#   backend/scripts/fetch_llm_model.sh [target_dir]        (default ./models)
#
# Serve it with llama.cpp (docker-compose profile "local-llm") or
#   pip install "llama-cpp-python[server]"
#   python -m llama_cpp.server --model models/qwen3-4b-instruct-2507-q4_k_m.gguf --port 8090 --n_ctx 8192
# then LOCAL_LLM_BASE_URL=http://<host>:8090/v1/chat/completions and LLM_PROVIDERS=groq,local
set -euo pipefail
TARGET="${1:-./models}"
REPO=ai/qwen3
TAG="${KEEL_LLM_MODEL_TAG:-4b-instruct-2507-q4_K_M}"
mkdir -p "$TARGET"
cd "$TARGET"
token() { curl -fsS "https://auth.docker.io/token?service=registry.docker.io&scope=repository:$REPO:pull" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])"; }
DIGEST=$(curl -fsS -H "Authorization: Bearer $(token)" -H "Accept: application/vnd.oci.image.manifest.v1+json" \
  "https://registry-1.docker.io/v2/$REPO/manifests/$TAG" | python3 -c "
import sys,json; d=json.load(sys.stdin); print(max(d['layers'], key=lambda l: l['size'])['digest'])")
echo "model layer: $DIGEST"
curl -fL -C - --retry 5 -H "Authorization: Bearer $(token)" -o model.gguf.part "https://registry-1.docker.io/v2/$REPO/blobs/$DIGEST"
GOT="sha256:$(sha256sum model.gguf.part | cut -d' ' -f1)"
[ "$GOT" = "$DIGEST" ] || { echo "DIGEST MISMATCH: $GOT"; exit 1; }
mv model.gguf.part qwen3-4b-instruct-2507-q4_k_m.gguf
echo "ready: $(pwd)/qwen3-4b-instruct-2507-q4_k_m.gguf"
