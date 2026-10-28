"""
One process-wide lock for importing ML libraries and loading models.

Found in first-customer acceptance testing: importing a review file starts
sentiment analysis in a background thread (transformers) while a PDF upload
in a request thread loads the RAG embedder (sentence_transformers, which
imports transformers too). Two threads importing the same large package at
once can see it half-initialised - the upload failed with "cannot import
name 'is_torch_npu_available' from 'transformers'" and that document never
reached the assistant. Serialising first-time imports/loads also stops two
requests from loading the same ~1 GB model twice.
"""
import logging
import threading

logger = logging.getLogger("KEEL_ML_RUNTIME")

ML_LOAD_LOCK = threading.RLock()


_UNOBTAINABLE_UNTIL = {}  # model name -> monotonic time before which it isn't re-probed
UNOBTAINABLE_RETRY_SECONDS = 600


WEIGHT_FILES = ("model.safetensors", "pytorch_model.bin")


def model_obtainable(model_name: str, probe_timeout: float = 3.0, weights=WEIGHT_FILES) -> bool:
    """Cached wrapper: a model found unavailable isn't probed again for
    UNOBTAINABLE_RETRY_SECONDS, so a blocked host costs one probe per ten
    minutes instead of one per request. `weights` names the files the caller
    will load (an ONNX export instead of the torch weights, say)."""
    import time

    key = (model_name, tuple(weights))
    if _UNOBTAINABLE_UNTIL.get(key, 0) > time.monotonic():
        return False
    ok = _model_obtainable(model_name, probe_timeout, tuple(weights))
    if not ok:
        _UNOBTAINABLE_UNTIL[key] = time.monotonic() + UNOBTAINABLE_RETRY_SECONDS
    return ok


def _model_obtainable(model_name: str, probe_timeout: float = 3.0, weights=WEIGHT_FILES) -> bool:
    """True when a Hugging Face model can be loaded: its files are already in
    the local cache, it is a local path, or the hub answers within
    `probe_timeout` seconds. Lets callers fail in seconds instead of sitting
    through the hub client's own retries (~100 s) when the host is blocked."""
    import os

    if not model_name or os.path.isdir(model_name):
        return True
    try:
        from huggingface_hub import try_to_load_from_cache

        # The weights, not just config.json - an interrupted download leaves
        # the small files cached and the weights as *.incomplete.
        for file_name in weights:
            if isinstance(try_to_load_from_cache(model_name, file_name), str):
                return True
    except Exception:  # noqa: BLE001 - library missing or odd cache: fall through to the probe
        pass
    if os.getenv("HF_HUB_OFFLINE") == "1":
        return False  # offline and the weights aren't cached: loading can only fail
    import urllib.error
    import urllib.request

    endpoint = os.getenv("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
    # Probe the weights download itself (it redirects to a separate file
    # host), not just the hub API - the API can be reachable while the file
    # host is blocked, which is exactly the slow-failure case.
    for file_name in weights:
        request = urllib.request.Request(f"{endpoint}/{model_name}/resolve/main/{file_name}", method="HEAD")
        try:
            urllib.request.urlopen(request, timeout=probe_timeout)
            return True
        except urllib.error.HTTPError as err:
            if err.code == 404:
                continue  # this repo ships the other weights format
            if err.code in (401, 403):
                # Public models need no token, but a token that is sent and has
                # expired or been revoked is refused - the host is reachable.
                logger.error("Hugging Face refused to download %s (HTTP %s): the access token sent with the "
                             "request (HF_TOKEN / HUGGINGFACE_HUB_TOKEN) is invalid or expired", model_name, err.code)
            return False
        except Exception:  # noqa: BLE001 - unreachable, refused, blocked
            return False
    return False
