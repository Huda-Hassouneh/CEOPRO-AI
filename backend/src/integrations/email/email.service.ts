import { sendVerificationEmailWithGmail } from "./gmail-smtp.client.js";
import type { EmailDeliveryProvider, VerificationEmailInput } from "./email.types.js";
import { sendVerificationEmail as sendWithResend } from "./resend.client.js";

type EmailProviderSenders = Record<
  EmailDeliveryProvider,
  (input: VerificationEmailInput) => Promise<void>
>;

const providerSenders: EmailProviderSenders = {
  gmail_smtp: sendVerificationEmailWithGmail,
  resend: sendWithResend
};

export function createEmailDeliveryService(
  senders: EmailProviderSenders = providerSenders
) {
  return async (input: VerificationEmailInput): Promise<void> => {
    const configuredProvider = process.env.EMAIL_DELIVERY_PROVIDER || "gmail_smtp";
    const provider = configuredProvider.trim().toLowerCase() as EmailDeliveryProvider;
    const sender = senders[provider];
    if (!sender) {
      throw new Error(`Unsupported EMAIL_DELIVERY_PROVIDER: ${configuredProvider}`);
    }
    await sender(input);
  };
}

export const sendVerificationEmail = createEmailDeliveryService();
