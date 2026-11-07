#!/bin/sh
# The processor on CPUs 0-1 only (the size of a free 2-vCPU host). Needs SECRET and CACHE.
cd "$(dirname "$0")/../../.."
exec taskset -c 0,1 env OFFLOAD_SHARED_SECRET="$SECRET" OFFLOAD_MAX_PARALLEL="${PAR:-2}" OFFLOAD_MAX_QUEUE="${QUEUE:-32}" \
  OVERTURE_EXECUTION=local OVERTURE_CACHE_DIR="$CACHE" OVERTURE_CACHE_SIGNING_KEY="$SECRET" \
  OFFLOAD_ENABLE_TEST_TASKS="${TEST_TASKS:-0}" OFFLOAD_WARM_OVERTURE="${WARM:-0}" \
  uvicorn src.offload.processor:app --host 127.0.0.1 --port "${PPORT:-7860}" --log-level warning
