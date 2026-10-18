export type VerificationEmailInput = {
  email: string;
  fullName?: string;
  token: string;
};

export type EmailDeliveryProvider = "gmail_smtp" | "resend";
