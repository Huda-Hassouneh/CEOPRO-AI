# KEEL — Recurring Consent Disclosure & Versioning (Draft)

> **DRAFT 0.1 — NOT APPROVED FOR LIVE ACCEPTANCE.** This is not a legal substitute for the payment provider's own Checkout disclosures. The actual text must be approved and dynamically populated from frozen server-side terms.

## Required display before acceptance
- Service and selected Standard/Custom Plan: **[[DYNAMIC_PLAN_NAME_AND_APPROVED_FEATURES]]**.
- Today’s charge: **[[DYNAMIC_INITIAL_CHARGE_AND_TAX]]**; charged currency: **[[DYNAMIC_CURRENCY]]**.
- Trial duration: **14 days for eligible Standard, Plus and Pro subscriptions**. Custom Plan eligibility and any trial must follow its approved quote. Start uses the authoritative provider-confirmed trial-start timestamp; Checkout completion alone is insufficient. Expected first nonzero charge: **[[DYNAMIC_FIRST_CHARGE_DATE]]**.
- Subsequent automatic renewal: **[[DYNAMIC_RENEWAL_AMOUNT_AND_TAX]]** every **[[DYNAMIC_BILLING_INTERVAL]]**, starting **[[DYNAMIC_RENEWAL_DATE]]**.
- How to cancel and effective date: **[[APPROVED_PROVIDER_SPECIFIC_CANCEL_INSTRUCTIONS]]**.
- Refund and withdrawal rights: **[[APPROVED_PROVIDER_SPECIFIC_REFUND_SUMMARY_AND_LINK]]**.
- The seller/Merchant of Record for this specific Checkout: **[[ORIGINAL_PROVIDER_AND_MERCHANT_OF_RECORD]]**.
- Links and version IDs: **[[TERMS_VERSION]]**, **[[PRIVACY_VERSION]]**, **[[REFUND_VERSION]]**, **[[SUBSCRIPTION_VERSION]]**.

## Suggested acceptance wording (requires owner/legal approval)
**Checkbox A — mandatory, initially unchecked:** “I have reviewed the plan, charges, trial (if applicable), automatic renewal schedule and cancellation terms. I agree to the applicable KEEL Terms and the selected payment provider’s purchase terms, and I authorize the recurring payments shown above.”

**Checkbox B — marketing (optional, separate, initially unchecked):** “I would like to receive optional product updates and marketing emails.” Do not bundle this with payment consent.

If no recurring charge is configured, the interface must not state that recurring authorization is being obtained. If the approval policy or payment mechanism is unresolved, disable acceptance rather than inserting placeholder terms.

## Acceptance records
The intended acceptance record identifies the authenticated customer, selected order, frozen commercial terms, document versions, language and acceptance time. Viewing these draft pages does not record acceptance or authorize payment.

## Withdrawal is a separate lifecycle
Pre-confirmation consent withdrawal and subsequent subscription cancellation are different actions. Withdrawal must prevent later local confirmation, but does not itself cancel a completed provider subscription. Public instructions and applicable withdrawal rights remain subject to **[[APPROVED_PUBLIC_WITHDRAWAL_INSTRUCTIONS_AND_RIGHTS]]**. Already-confirmed subscriptions require the applicable cancellation process.


---
