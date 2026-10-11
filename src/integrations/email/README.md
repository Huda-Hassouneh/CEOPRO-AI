# Email Integration

This folder sends CEO PRO verification emails. It builds one verification message and lets the application choose Gmail SMTP or Resend as the delivery provider.

## On this page

- [The email flow](#the-email-flow)
- [What each part does](#what-each-part-does)
- [Common scenarios](#common-scenarios)
- [Configuration](#configuration)
- [Security and delivery notes](#security-and-delivery-notes)
- [Testing checklist](#testing-checklist)

## The email flow

```text
Registration or verification-resend flow
        │  recipient, token, optional name
        ▼
sendVerificationEmail(input)
        │  selects provider from EMAIL_DELIVERY_PROVIDER
        ├───────────────┐
        ▼               ▼
   Gmail SMTP         Resend API
        └───────┬───────┘
                ▼
      Verification email in the user's inbox
```

The delivery service selects the provider; each provider client handles the actual send. The verification content module builds the subject, plain-text body, HTML body, and frontend verification link.

## What each part does

| Part                            | Responsibility                                                                                                                       |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `email.types.ts`                | Defines the email input and supported provider names.                                                                                |
| `verification-email.content.ts` | Builds the verification URL and returns the subject, text, and HTML content. Escapes dynamic values before inserting them into HTML. |
| `gmail-smtp.client.ts`          | Connects to Gmail using TLS and SMTP commands, authenticates, sends a MIME message, and checks SMTP replies.                         |
| `resend.client.ts`              | Sends the verification message to Resend's email API using `fetch`.                                                                  |
| Email delivery service          | Reads `EMAIL_DELIVERY_PROVIDER`, chooses Gmail or Resend, and exposes `sendVerificationEmail` to the rest of the backend.            |

The Resend client explicitly uses `createVerificationEmailContent`. The Gmail client wraps the message in MIME; keep its MIME body aligned with the same content builder so both providers send the same copy and verification link.

## Common scenarios

### 1. Send through the default provider

If `EMAIL_DELIVERY_PROVIDER` is unset, the delivery service uses `gmail_smtp`. The Gmail client reads its credentials, opens a TLS connection, authenticates, and sends the message through SMTP.

### 2. Switch to Resend

Set `EMAIL_DELIVERY_PROVIDER=resend`. The Resend client requires `EMAIL_SERVICE_PROVIDER_API_KEY`; it uses `EMAIL_SERVICE_PROVIDER_FROM_EMAIL` as the sender. If no sender is configured, it falls back to `CEO PRO <onboarding@resend.dev>`, which the code identifies as a development sender. Production should use an address on a domain verified in Resend.

### 3. The verification URL is generated

The content builder uses `FRONTEND_URL` (or `http://localhost:5173` when unset) and appends `/verify-email?token=...`. Confirm that this path matches the frontend route in the environment where the email is sent. The message says the link expires in 30 minutes, so the backend token's actual expiry should match.

### 4. A provider is misconfigured or rejects the email

- An unknown `EMAIL_DELIVERY_PROVIDER` produces an unsupported-provider error.
- Resend fails early if its API key is missing, and reports its HTTP status if the API rejects the request.
- Gmail can fail during TLS connection, SMTP authentication, recipient acceptance, or message delivery. The SMTP reply reader and `expectReply` validate the expected server responses.

Provider failures should be handled by the caller using the backend's normal error and retry policy. Do not silently report that verification email was sent when delivery failed.

## Configuration

| Variable                            | Used by          | Purpose                                                                                                                                                                                            |
| ----------------------------------- | ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `EMAIL_DELIVERY_PROVIDER`           | Delivery service | Selects `gmail_smtp` or `resend`; defaults to `gmail_smtp`.                                                                                                                                        |
| `EMAIL_SERVICE_PROVIDER_API_KEY`    | Resend           | Resend API credential. Required when Resend is selected.                                                                                                                                           |
| `EMAIL_SERVICE_PROVIDER_FROM_EMAIL` | Resend           | Sender address. Use an address on a verified domain in production.                                                                                                                                 |
| `FRONTEND_URL`                      | Content builder  | Base URL for the frontend verification route. Defaults to `http://localhost:5173`.                                                                                                                 |
| Gmail SMTP settings                 | Gmail client     | `SMTP_HOST`, `SMTP_PORT`, `SMTP_TIMEOUT_MS`, and credentials are referenced by the Gmail implementation. Verify their exact environment variable names in `getCredentials` and the SMTP constants. |

Keep provider selection and secrets in server-side environment configuration. Do not put API keys or Gmail credentials in frontend variables.

## Security and delivery notes

- The verification token is a bearer link: anyone who has it may be able to verify the account. Avoid logging the full URL or token.
- The HTML template escapes the display name and URL before inserting them into HTML. Keep this escaping if the template changes.
- Gmail's `AUTH LOGIN` values are Base64-encoded, not encrypted by Base64. TLS protects the SMTP connection in transit.
- The Resend client deliberately avoids logging API keys, message bodies, or provider response bodies; preserve that behavior.
- Gmail SMTP and Resend are separate delivery providers with separate sending limits and deliverability rules. Writing SMTP commands directly does not increase Gmail's sending quota.
- The development fallback sender at `onboarding@resend.dev` should not be treated as the production sender identity.

## Testing checklist

- The default provider is Gmail SMTP when `EMAIL_DELIVERY_PROVIDER` is unset.
- `gmail_smtp` and `resend` each select the intended sender; unsupported values fail clearly.
- Resend rejects a missing API key and sends the expected `from`, recipient, subject, text, and HTML fields when configured.
- The generated URL uses the configured frontend origin, the expected `/verify-email` path, and a safely encoded token query parameter.
- HTML output escapes special characters in the display name and URL.
- Gmail SMTP checks the server's expected response codes and closes the socket on success or failure.
- Provider failures do not expose credentials, verification tokens, full message content, or raw upstream response bodies in logs.
- The stated 30-minute expiration matches the actual verification-token expiry.
