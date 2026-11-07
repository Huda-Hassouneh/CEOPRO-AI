"""Explicit payment adapter composition; no provider selection or DB migration."""
from src.ai.billing.payment_contracts import PaymentWebhookDecoder, SubscriptionPaymentGateway
from src.ai.billing.stripe_gateway import StripeGateway
from src.ai.billing.stripe_webhooks import StripeWebhookDecoder


def payment_gateway() -> SubscriptionPaymentGateway:
    return StripeGateway()


def webhook_decoder(signing_secret: str) -> PaymentWebhookDecoder:
    return StripeWebhookDecoder(signing_secret)


def webhook_signature(request) -> str | None:
    return request.headers.get(StripeWebhookDecoder.signature_header)
