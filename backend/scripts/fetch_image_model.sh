#!/usr/bin/env bash
# Downloads Stable Diffusion XL 1.0 base (Stability AI; licence CreativeML Open
# RAIL++-M - commercial use allowed within its use restrictions) for the KEEL
# image server, free and without any account, from Docker Hub's official model
# catalog (docker.io/ai/stable-diffusion). Checks the download against the
# registry's sha256 digest, then unpacks the DDUF archive (a plain ZIP of the
# standard diffusers folder) into <target>/sdxl-base-1.0.
#
#   backend/scripts/fetch_image_model.sh [target_dir]      (default ./models)
#
# Needs: curl, python3, about 14 GB free during the download (6.9 GB archive +
# 6.5 GB unpacked; the archive is deleted afterwards).
set -euo pipefail
TARGET="${1:-./models}"
REPO=ai/stable-diffusion
TAG="${KEEL_IMAGE_MODEL_TAG:-latest}"   # latest = FP16 (CPU or GPU); Q4 = 4-bit, needs an NVIDIA GPU (bitsandbytes)
mkdir -p "$TARGET"
cd "$TARGET"
token() { curl -fsS "https://auth.docker.io/token?service=registry.docker.io&scope=repository:$REPO:pull" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])"; }
DIGEST=$(curl -fsS -H "Authorization: Bearer $(token)" -H "Accept: application/vnd.oci.image.manifest.v1+json" \
  "https://registry-1.docker.io/v2/$REPO/manifests/$TAG" | python3 -c "import sys,json;print(json.load(sys.stdin)['layers'][0]['digest'])")
echo "model layer: $DIGEST"
for attempt in 1 2 3 4 5 6; do
  if curl -fL -C - --retry 3 -H "Authorization: Bearer $(token)" -o model.dduf.part \
       "https://registry-1.docker.io/v2/$REPO/blobs/$DIGEST"; then break; fi
  echo "download interrupted (attempt $attempt); resuming"; sleep 5
done
echo "checking digest..."
GOT="sha256:$(sha256sum model.dduf.part | cut -d' ' -f1)"
[ "$GOT" = "$DIGEST" ] || { echo "DIGEST MISMATCH: $GOT"; exit 1; }
python3 -c "import zipfile; zipfile.ZipFile('model.dduf.part').extractall('sdxl-base-1.0')"
rm model.dduf.part
echo "ready: $(pwd)/sdxl-base-1.0  ->  KEEL_IMAGE_MODEL_DIR=$(pwd)/sdxl-base-1.0"
