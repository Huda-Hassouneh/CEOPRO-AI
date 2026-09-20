# Stripe Webhooks

## 1. Endpoint Details

`POST /stripe/webhooks/`

## 2. Mental Model

Stripe calls this endpoint after billing events. The route verifies the signed event, dispatches subscription/invoice lifecycle work, and records webhook events so subscription state and billing history converge with Stripe asynchronously.

## 3. Technical Decisions

The route is mounted before `express.json()` and uses `express.raw({ type: "application/json" })`; Stripe signature verification requires the untouched bytes. `validateWebhook` constructs the Stripe event with `STRIPE_SECRET_WEBHOOK`. Processing failures return `500` so Stripe retries. Successful duplicate detection is surfaced in the response by the webhook service.

## 4. Inputs

- Required header: `Stripe-Signature: <Stripe signature>`.
- Body: raw `application/json` bytes containing a Stripe Event. The event type and object are provider-defined; no JSON DTO is applied before signature verification.
- Path/query: none.

## 5. Outputs

### Success

`200 OK`

```json
{ "received": true, "duplicate": false }
```

`duplicate` may be `true` when the event was already recorded/handled.

### Errors

`400 Bad Request`:

```json
{
  "success": false,
  "error": {
    "message": "webhook signature is required",
    "statusCode": 400,
    "code": "INVALID_WEBHOOK_HEADER"
  }
}
```

`500 Internal Server Error` when event handling fails, intentionally causing Stripe retry:

```json
{ "success": false, "error": "<service error message>" }
```
