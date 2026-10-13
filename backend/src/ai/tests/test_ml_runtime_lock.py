"""
Concurrent first use of the ML models (sentiment in a background thread
while a request loads the RAG embedder) failed in acceptance testing with a
half-initialised-import error. The loaders now serialise first-time
imports/loads: a model is constructed exactly once even when many threads
ask for it at the same moment.
"""
import sys
import threading
import time
import types

from src.ai.rag import embeddings


def test_concurrent_first_use_loads_the_embedder_exactly_once(monkeypatch):
    constructed = []

    class SlowSentenceTransformer:
        def __init__(self, name):
            time.sleep(0.2)  # a real load takes seconds
            constructed.append(name)

    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = SlowSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    monkeypatch.setattr(embeddings, "_model_cache", {})

    results = []
    threads = [threading.Thread(target=lambda: results.append(embeddings.get_model("fake-model"))) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert constructed == ["fake-model"]
    assert len({id(model) for model in results}) == 1
