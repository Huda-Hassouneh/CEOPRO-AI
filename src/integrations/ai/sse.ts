import { createAiIntegrationError } from "./ai.types.js";

type SseFrame = {
  event: string;
  data: string;
};

function parseFrame(frameText: string): SseFrame | null {
  let event = "message";
  const data: string[] = [];

  for (const line of frameText.split(/\r?\n/)) {
    if (!line || line.startsWith(":")) continue;
    const separator = line.indexOf(":");
    const field = separator < 0 ? line : line.slice(0, separator);
    let value = separator < 0 ? "" : line.slice(separator + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "event") event = value;
    if (field === "data") data.push(value);
  }

  if (data.length === 0) return null;
  return { event, data: data.join("\n") };
}

function resultFromFrame(frameText: string):
  | { done: true; value: unknown }
  | { done: false } {
  const frame = parseFrame(frameText);
  if (!frame) return { done: false };

  if (frame.event === "error") {
    throw createAiIntegrationError(
      "The Gradio AI job returned an error event.",
      "upstream_event"
    );
  }

  if (frame.event !== "complete") return { done: false };

  let payload: unknown;
  try {
    payload = JSON.parse(frame.data);
  } catch {
    throw createAiIntegrationError(
      "The Gradio AI service returned malformed SSE JSON.",
      "malformed_response"
    );
  }

  if (!Array.isArray(payload) || payload.length !== 1) {
    throw createAiIntegrationError(
      "The Gradio AI service returned an invalid completion payload.",
      "malformed_response"
    );
  }

  return { done: true, value: payload[0] };
}

export async function readGradioSseResult(
  stream: ReadableStream<Uint8Array>,
  timeoutMs?: number
): Promise<unknown> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  let streamClosed = false;
  let timedOut = false;
  const timeout = timeoutMs
    ? setTimeout(() => {
        timedOut = true;
        void reader.cancel();
      }, timeoutMs)
    : undefined;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (timedOut) {
        throw createAiIntegrationError(
          `The Gradio SSE stream timed out after ${timeoutMs} ms.`,
          "timeout"
        );
      }
      if (done) {
        streamClosed = true;
        break;
      }
      pending += decoder.decode(value, { stream: true });

      let boundary = /\r?\n\r?\n/.exec(pending);
      while (boundary) {
        const frameText = pending.slice(0, boundary.index);
        pending = pending.slice(boundary.index + boundary[0].length);
        const result = resultFromFrame(frameText);
        if (result.done) return result.value;
        boundary = /\r?\n\r?\n/.exec(pending);
      }
    }

    pending += decoder.decode();
    if (pending.trim()) {
      const finalResult = resultFromFrame(pending);
      if (finalResult.done) return finalResult.value;
    }

    throw createAiIntegrationError(
      "The Gradio SSE stream ended without a complete event.",
      "malformed_response"
    );
  } catch (error) {
    if (error instanceof Error && error.name === "AiIntegrationError") {
      throw error;
    }
    if (timedOut) {
      throw createAiIntegrationError(
        `The Gradio SSE stream timed out after ${timeoutMs} ms.`,
        "timeout"
      );
    }
    throw createAiIntegrationError(
      "The Gradio SSE stream could not be read.",
      "malformed_response"
    );
  } finally {
    if (timeout) clearTimeout(timeout);
    if (!streamClosed) {
      try {
        await reader.cancel();
      } catch {
        // The stream may already have been canceled by the timeout handler.
      }
    }
    reader.releaseLock();
  }
}
