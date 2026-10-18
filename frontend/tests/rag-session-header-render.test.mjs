import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { RagSessionHeader } from "../src/features/knowledge-base/components/RagSessionHeader.jsx";

for (const locale of ["en", "ar"]) {
  const messages = JSON.parse(readFileSync(new URL(`../src/assets/locales/${locale}.json`, import.meta.url)));
  const t = (key) => {
    const value = key.split(".").reduce((node, part) => node?.[part], messages);
    assert.equal(typeof value, "string", `Missing ${locale}:${key}`);
    return value;
  };
  const props = {
    sessions: [], sessionId: null, messages: [], loading: false,
    loadingConversation: false, sending: false, error: null,
    onSelect() {}, onNew() {}, onRetry() {}, t
  };
  const render = (overrides = {}) => renderToStaticMarkup(React.createElement(RagSessionHeader, { ...props, ...overrides }));

  test(`${locale}: empty history explains how to begin and keeps New conversation available`, () => {
    const html = render();
    assert.ok(html.includes(t("ragAssistant.history.empty")));
    assert.ok(html.includes(t("ragAssistant.history.noHistory")));
    assert.match(html, /<select[^>]*disabled/);
    assert.match(html, /<button[^>]*>.*?New conversation|<button[^>]*>.*?محادثة جديدة/s);
    assert.ok(html.includes(t("ragAssistant.history.switch")));
  });

  test(`${locale}: selected saved conversation is identifiable and titles are safe`, () => {
    const title = `<Quarterly report & operations> ${"detail ".repeat(20)}`;
    const html = render({
      sessionId: "saved-1",
      sessions: [
        { session_id: "saved-1", title },
        { session_id: "saved-2", title: "" }
      ]
    });
    assert.match(html, /<option value="saved-1" selected=""/);
    assert.ok(html.includes("&lt;Quarterly report &amp; operations&gt;"));
    assert.ok(!html.includes("<Quarterly report"));
    assert.ok(html.includes(t("ragAssistant.history.untitled")));
    assert.match(html, /class="rag-session-header__title"[^>]*title=/);
    assert.match(html, /<label[^>]*for=/);
  });

  test(`${locale}: active session remains named before the refreshed list includes it`, () => {
    const html = render({ sessionId: "just-created", messages: [{ role: "user", content: "How many sales?" }] });
    assert.ok(html.includes("How many sales?"));
    assert.match(html, /<option value="just-created"/);
    assert.ok(!html.includes(t("ragAssistant.history.noHistory")));
  });

  test(`${locale}: loading and failed switches explain what happened and allow retry`, () => {
    const loading = render({ loading: true, loadingConversation: true });
    assert.ok(loading.includes(t("ragAssistant.history.loading")));
    assert.match(loading, /role="status"/);
    assert.match(loading, /<select[^>]*disabled/);
    const error = render({ error: "switch", sessions: [{ session_id: "one", title: "Saved" }] });
    assert.ok(error.includes(t("ragAssistant.history.openFailed")));
    assert.ok(error.includes(t("ragAssistant.history.retryLoad")));
    assert.match(error, /role="alert"/);
    const listError = render({ error: "list" });
    assert.ok(listError.includes(t("ragAssistant.history.loadFailed")));
    assert.ok(listError.includes(t("ragAssistant.history.historyUnavailable")));
    assert.ok(!listError.includes(t("ragAssistant.history.noHistory")));
  });
}
