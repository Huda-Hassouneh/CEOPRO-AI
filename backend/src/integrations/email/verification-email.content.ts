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
  const fullName = input.fullName?.replace(/[\r\n]+/g, " ").trim();
  const greetingText = fullName ? `Hello ${fullName},` : "Hello,";
  const greetingHtml = escapeHtml(greetingText);
  const safeUrl = escapeHtml(verificationUrl);

  return {
    subject: "Verify your KEEL email",
    text: `${greetingText}

Thanks for creating a KEEL account. Please verify your email address to finish setting up your account:

${verificationUrl}

This link expires in 30 minutes. If you didn’t request this account, you can safely ignore this email.`,
    html: `<!doctype html>
<html lang="en">
  <body style="margin:0;padding:0;background:#f3f0fe;font-family:Inter,'Segoe UI',Arial,sans-serif;color:#1d1d2a;">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">
      Verify your email address to finish setting up your KEEL account.
    </div>

    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f3f0fe;">
      <tr>
        <td align="center" style="padding:36px 16px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:440px;background:#ffffff;border:1px solid #dfe3f1;border-top:4px solid #2f2bce;border-radius:14px;box-shadow:0 20px 48px -28px rgba(47,43,206,0.26);">
            <tr>
              <td align="center" style="padding:32px 28px 12px;">
                <div style="color:#2f2bce;font-size:20px;font-weight:800;letter-spacing:-0.3px;">
                  KEEL
                </div>
              </td>
            </tr>

            <tr>
              <td style="padding:12px 32px 32px;">
                <h1 style="margin:0 0 12px;color:#19182a;font-size:25px;line-height:1.25;font-weight:800;letter-spacing:-0.5px;text-align:center;">
                  Verify your email
                </h1>

                <p style="margin:0 0 12px;color:#4b4d5f;font-size:14px;line-height:1.6;">
                  ${greetingHtml}
                </p>

                <p style="margin:0 0 24px;color:#747386;font-size:14px;line-height:1.6;text-align:center;">
                  Thanks for creating a KEEL account. Confirm your email address to finish setting up your account.
                </p>

                <table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center" style="margin:0 auto 24px;">
                  <tr>
                    <td align="center" style="background:#2f2bce;border-radius:9px;">
                      <a href="${safeUrl}" style="display:inline-block;min-width:190px;padding:14px 22px;border:1px solid #2f2bce;border-radius:9px;color:#ffffff;text-decoration:none;font-size:14px;line-height:18px;font-weight:600;text-align:center;">
                        Verify email address
                      </a>
                    </td>
                  </tr>
                </table>

                <p style="margin:0 0 10px;padding:12px 14px;border:1px solid #dfe3f1;border-radius:10px;background:#F5F2FF;color:#4b4d5f;font-size:13px;line-height:1.55;">
                  For your security, this link expires in <strong style="color:#1d1d2a;">30 minutes</strong>.
                </p>

                <p style="margin:0;color:#7a7d8d;font-size:13px;line-height:1.55;text-align:center;">
                  If you didn’t request a KEEL account, you can safely ignore this email.
                </p>

                <hr style="height:1px;margin:24px 0 16px;border:0;background:#dfe3f1;">

                <p style="margin:0 0 6px;color:#7a7d8d;font-size:11px;line-height:1.5;">
                  If the button doesn’t work, copy and paste this link into your browser:
                </p>
                <a href="${safeUrl}" style="color:#2f2bce;font-size:11px;line-height:1.5;word-break:break-all;">
                  ${safeUrl}
                </a>
              </td>
            </tr>
          </table>

          <p style="margin:16px 0 0;color:#7a7d8d;font-size:11px;line-height:1.5;text-align:center;">
            This is an automated message from KEEL. Please don’t reply to this email.
          </p>
        </td>
      </tr>
    </table>
  </body>
</html>`
  };
}
