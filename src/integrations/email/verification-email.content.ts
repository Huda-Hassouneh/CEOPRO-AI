import type { VerificationEmailInput } from "./email.types.js";

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => {
    const entities: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    };
    return entities[character] ?? character;
  });
}

export function getVerificationEmailUrl(token: string): string {
  const frontendBaseUrl = (
    process.env.FRONTEND_URL || "http://localhost:5173"
  ).replace(/\/$/, "");
  const url = new URL(`${frontendBaseUrl}/verify-email`);
  url.searchParams.set("token", token);
  return url.toString();
}

export function createVerificationEmailContent(input: VerificationEmailInput) {
  const verificationUrl = getVerificationEmailUrl(input.token);
  const greeting = input.fullName
    ? `Hello ${escapeHtml(input.fullName)},`
    : "Hello,";
  const safeUrl = escapeHtml(verificationUrl);

  return {
    subject: "Verify your CEO PRO email",
    text: `${input.fullName ? `Hello ${input.fullName},\n\n` : "Hello,\n\n"}Verify your email address to create your CEO PRO account: ${verificationUrl}\n\nThis link expires in 30 minutes. If you did not request this, ignore this email.`,
    html: `<div style="font-family:Arial,sans-serif;line-height:1.6;color:#172033;max-width:560px;margin:auto"><h1 style="font-size:24px">Verify your email</h1><p>${greeting}</p><p>Confirm your email address to create your CEO PRO account.</p><p><a href="${safeUrl}" style="display:inline-block;padding:12px 20px;border-radius:8px;background:#1546a0;color:#fff;text-decoration:none">Verify email</a></p><p>This link expires in 30 minutes. If you did not request this, you can ignore this email.</p></div>`
  };
}
