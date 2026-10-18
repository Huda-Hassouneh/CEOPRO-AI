import test from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import {
  assertStripeTestEnvironment,
  disconnectDb,
  loadCeopro,
  makeEvent,
  TEST_WEBHOOK_SECRET,
} from "./_stripe-e2e-helpers.js";

assertStripeTestEnvironment();

test("13.01 webhook route verifies Stripe signature and deduplicates repeated events", async () => {
  const { prisma, stripe } = await loadCeopro();
  const event = makeEvent({
    type: "customer.created",
    object: { id: "cus_ceopro_signature_test", object: "customer" },
  });
  const payload = JSON.stringify(event);
  const signature = stripe.webhooks.generateTestHeaderString({ payload, secret: TEST_WEBHOOK_SECRET });

  const { default: app } = await import("../../../src/app.js");
  const server = http.createServer(app);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address !== "string");
  const url = `http://127.0.0.1:${address.port}/stripe/webhooks`;

  try {
    const first = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json", "stripe-signature": signature },
      body: payload,
    });
    assert.equal(first.status, 200);
    assert.deepEqual(await first.json(), { received: true, duplicate: false });

    const second = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json", "stripe-signature": signature },
      body: payload,
    });
    assert.equal(second.status, 200);
    assert.deepEqual(await second.json(), { received: true, duplicate: true });

    const bad = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json", "stripe-signature": "bad" },
      body: payload,
    });
    assert.ok(bad.status >= 400, "invalid Stripe signatures must be rejected");

    const rows = await prisma.payment_providerWebhookEvent.findMany({
      where: { payment_providerEventId: event.id },
    });
    assert.equal(rows.length, 1);
    assert.equal(rows[0].processed, true);
  } finally {
    await prisma.payment_providerWebhookEvent.deleteMany({
      where: { payment_providerEventId: event.id },
    });
    await new Promise<void>((resolve, reject) =>
      server.close((error) => (error ? reject(error) : resolve())),
    );
    await disconnectDb();
  }
});
