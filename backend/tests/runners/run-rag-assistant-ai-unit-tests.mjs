import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

const python = process.platform === "win32" ? "python" : "python3";
const aiRoot = resolve(process.cwd(), "../ai");
const tests = [
  "src/ai/tests/test_rag_chunking.py",
  "src/ai/tests/test_rag_pipeline.py",
  "src/ai/tests/test_rag_embeddings.py",
  "src/ai/tests/test_rag_bm25_index.py",
  "src/ai/tests/test_rag_faiss_index.py",
  "src/ai/tests/test_rag_hybrid_retrieval.py",
  "src/ai/tests/test_rag_reranking.py",
  "src/ai/tests/test_rag_llm_client.py"
];
const result = spawnSync(python, ["-m", "pytest", "-q", ...tests], {
  cwd: aiRoot,
  stdio: "inherit",
  shell: process.platform === "win32",
  env: process.env
});
if (result.error) console.error(`AI-team RAG unit tests unavailable: ${result.error.message}`);
if (result.error || result.status !== 0) process.exitCode = 1;
