import type { VerificationEmailInput } from "./email.types.js";
import { createVerificationEmailContent, getVerificationEmailUrl } from "./verification-email.content.js";

const RESEND_EMAILS_URL = "https://api.resend.com/emails";

export { getVerificationEmailUrl as getEmailVerificationUrl };

export async function sendVerificationEmail(input: VerificationEmailInput): Promise<void> {
  const apiKey = process.env.EMAIL_SERVICE_PROVIDER_API_KEY?.trim();
  if (!apiKey) {
    throw new Error("EMAIL_SERVICE_PROVIDER_API_KEY is not configured");
  }

  // Resend's test sender works for initial development. Production must set
  // this to an address on a domain verified in the Resend dashboard.
  const from =
    process.env.EMAIL_SERVICE_PROVIDER_FROM_EMAIL?.trim() ||
    "CEO PRO <onboarding@resend.dev>";
  const content = createVerificationEmailContent(input);

  const response = await fetch(RESEND_EMAILS_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json"
    },
    signal: AbortSignal.timeout(10_000),
    body: JSON.stringify({
      from,
      to: [input.email],
      ...content
    })
  });

  if (!response.ok) {
    // Do not log API keys, full message bodies, or provider response bodies.
    throw new Error(`Resend rejected the verification email (${response.status})`);
  }
}
