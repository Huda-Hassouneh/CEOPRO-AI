import assert from "node:assert/strict";
import test from "node:test";
import {
  getGradioRuntimeConfig,
  isAiMockModeEnabled
} from "../../../src/integrations/ai/config.js";

const baseEnv = { HUGGINGFACE_ACCESS_TOKEN: " hf-test-token " };

test("AI config selects the defaults for each Gradio Space", () => {
  const models = getGradioRuntimeConfig("models", baseEnv);
  const analytics = getGradioRuntimeConfig("analytics", baseEnv);
  assert.equal(models.service.spaceId, "hhuuddaa/ceopro-ai-models");
  assert.equal(models.service.baseUrl, "https://hhuuddaa-ceopro-ai-models.hf.space");
  assert.equal(analytics.service.spaceId, "hhuuddaa/ceopro-ai-analytics");
  assert.equal(models.huggingFaceAccessToken, "hf-test-token");
  assert.equal(models.timeoutMs, 180_000);
});

test("AI config applies trimmed environment overrides", () => {
  const config = getGradioRuntimeConfig("models", {
    ...baseEnv,
    AI_MODELS_SPACE: " org/my-space ",
    AI_MODELS_SPACE_URL: "https://example.test/ ",
    HUGGINGFACE_API_URL: "https://hub.example.test/",
    AI_SERVICE_TIMEOUT_MS: "45000"
  });
  assert.equal(config.service.spaceId, "org/my-space");
  assert.equal(config.service.baseUrl, "https://example.test");
  assert.equal(config.huggingFaceApiUrl, "https://hub.example.test");
  assert.equal(config.timeoutMs, 45_000);
});

test("AI config rejects missing credentials, invalid URLs, and unsafe production URLs", () => {
  assert.throws(() => getGradioRuntimeConfig("models", {}), /HUGGINGFACE_ACCESS_TOKEN/);
  assert.throws(
    () => getGradioRuntimeConfig("models", { ...baseEnv, AI_MODELS_SPACE_URL: "not a URL" }),
    /valid HTTP or HTTPS URL/
  );
  assert.throws(
    () => getGradioRuntimeConfig("models", { ...baseEnv, NODE_ENV: "production", AI_MODELS_SPACE_URL: "http://example.test" }),
    /HTTPS in production/
  );
});

test("AI config validates timeout bounds and blocks production mocks", () => {
  for (const timeout of ["999", "600001", "1.5", "invalid"]) {
    assert.throws(
      () => getGradioRuntimeConfig("models", { ...baseEnv, AI_SERVICE_TIMEOUT_MS: timeout }),
      /integer between 1000 and 600000/
    );
  }
  assert.throws(
    () => getGradioRuntimeConfig("models", { ...baseEnv, NODE_ENV: "production", AI_SERVICE_USE_MOCKS: "true" }),
    /disabled in production/
  );
  assert.equal(isAiMockModeEnabled({ AI_SERVICE_USE_MOCKS: " TRUE " }), true);
  assert.equal(isAiMockModeEnabled({}), false);
});
