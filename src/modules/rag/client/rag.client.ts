import { z } from "zod";
import { gradioClient } from "../../../integrations/ai/gradio.client.js";
import type { GradioClient } from "../../../integrations/ai/ai.types.js";
import {
  createAiIntegrationError,
  isAiIntegrationError
} from "../../../integrations/ai/ai.types.js";
import {
  ragQueryResponseSchema,
  type RagQueryResponse
} from "../types/rag.types.js";

const ragAnswerInputSchema = z.object({
  documents: z
    .array(
      z.union([
        z.object({ file_name: z.string().min(1), text: z.string().min(1) }),
        z.object({
          file_name: z.string().min(1),
          content_base64: z.string().min(1)
        })
      ])
    )
    .min(1)
    .max(10),
  question: z.string().trim().min(1).max(2000),
  top_k: z.number().int().min(1).max(20),
  history: z
    .array(z.object({ role: z.string(), content: z.string() }))
    .nullable()
});

export type RagAiDocument = z.infer<
  typeof ragAnswerInputSchema
>["documents"][number];
export { isAiIntegrationError as isRagClientError };

export function buildRagAnswerData(input: {
  documents: RagAiDocument[];
  queryText: string;
  topK: number;
  history: Array<{ role: string; content: string }> | null;
}): unknown[] {
  return [input.documents, input.queryText, input.topK, input.history];
}

export async function queryRagAi(
  input: {
    documents: RagAiDocument[];
    queryText: string;
    topK: number;
    history: Array<{ role: string; content: string }> | null;
  },
  client: GradioClient = gradioClient
): Promise<RagQueryResponse> {
  const parsedInput = ragAnswerInputSchema.safeParse({
    documents: input.documents,
    question: input.queryText,
    top_k: input.topK,
    history: input.history
  });
  console.log({ ai_query_parsed: parsedInput });

  if (!parsedInput.success) {
    throw createAiIntegrationError(
      "RAG request does not match the documented Gradio input schema.",
      "configuration"
    );
  }

  const payload = await client.call({
    service: "models",
    apiName: "rag_answer",
    data: buildRagAnswerData(input),
    timeoutMs: 120_000
  });
  const parsed = ragQueryResponseSchema.safeParse(payload);

  if (!parsed.success) {
    throw createAiIntegrationError(
      "Gradio RAG response did not match the documented output schema.",
      "malformed_response"
    );
  }
  return parsed.data;
}
