import assert from "node:assert/strict";
import test from "node:test";
import { isAiIntegrationError } from "../../src/integrations/ai/ai.types.js";
import { buildRagAnswerData, queryRagAi } from "../../src/modules/rag/client/rag.client.js";

const documents = [
  { file_name: "doc-1_Refund Policy.txt", text: "Damaged items may be returned within 14 days." }
];

test("RAG adapter serializes the active Gradio positional contract including optional history", async () => {
  const calls: Array<Record<string, unknown>> = [];
  const result = await queryRagAi({
    documents,
    queryText: "What is the return period?",
    topK: 3,
    history: [{ role: "user", content: "What is the policy?" }]
  }, {
    async call(input) {
      calls.push(input as unknown as Record<string, unknown>);
      return {
        answer: "14 days.",
        sources: [{ source_index: 0, document: "doc-1_Refund Policy.txt", chunk_index: 0, text: "Returned within 14 days.", score: 0.9 }],
        token_usage: { prompt_tokens: 30, completion_tokens: 4, total_tokens: 34 }
      };
    }
  });
  assert.deepEqual(buildRagAnswerData({ documents, queryText: "Q", topK: 3, history: null }), [documents, "Q", 3, null]);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].service, "models");
  assert.equal(calls[0].apiName, "rag_answer");
  assert.equal(calls[0].timeoutMs, 120_000);
  assert.deepEqual(calls[0].data, [documents, "What is the return period?", 3, [{ role: "user", content: "What is the policy?" }]]);
  assert.equal(result.answer, "14 days.");
  assert.equal(result.token_usage?.total_tokens, 34);
});

test("RAG adapter rejects empty, oversized, or malformed requests before any provider call", async () => {
  let calls = 0;
  const fake = { async call() { calls += 1; return { answer: "ok", sources: [] }; } };
  await assert.rejects(queryRagAi({ documents: [], queryText: "q", topK: 3, history: null }, fake), isAiIntegrationError);
  await assert.rejects(queryRagAi({ documents: Array.from({ length: 11 }, (_, i) => ({ file_name: `d${i}.txt`, text: "x" })), queryText: "q", topK: 3, history: null }, fake), isAiIntegrationError);
  await assert.rejects(queryRagAi({ documents, queryText: " ", topK: 3, history: null }, fake), isAiIntegrationError);
  assert.equal(calls, 0);
});

test("RAG adapter rejects a malformed upstream response instead of fabricating a citation", async () => {
  await assert.rejects(queryRagAi({ documents, queryText: "question", topK: 3, history: null }, {
    async call() { return { answer: 42, sources: [{ chunk_id: "invented" }] }; }
  }), (error: unknown) => isAiIntegrationError(error) && error.kind === "malformed_response");
});

test("RAG adapter propagates typed upstream failures for controller classification", async () => {
  await assert.rejects(queryRagAi({ documents, queryText: "question", topK: 3, history: null }, {
    async call() { const error = new Error("timeout") as Error & { name: string; kind: string }; error.name = "AiIntegrationError"; error.kind = "timeout"; throw error; }
  }), (error: unknown) => isAiIntegrationError(error) && error.kind === "timeout");
});

test('RAG adapter identifies empty hosted answers for actionable feedback and refund',async()=>{
 await assert.rejects(queryRagAi({documents,queryText:'Question',topK:3,history:null},{async call(){return {answer:'  ',sources:[],token_usage:{total_tokens:12}};}}),
  (error:unknown)=>isAiIntegrationError(error)&&'reason' in error&&error.reason==='ANSWER_EMPTY');
});
