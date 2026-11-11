# KEEL — Subscription, Trials and Cancellation Policy (Draft)

> **DRAFT 0.1 — NOT APPROVED.** No proposed duration or renewal policy below may become a system default without approval.

## 1. Subscription order
The binding order should identify the chosen Standard or eligible Custom Plan, approved features and limits, quantity, billed currency, charge amount, billing interval, transaction provider, applicable taxes, trial conditions and policy versions. Pricing Studio analysis currency is not necessarily the charge currency. A Custom quote is not an activated subscription.

## 2. Free trials
Standard, Plus and Pro each offer a 14-day trial to eligible businesses under the approved provider-backed program, with a payment method required and explicit recurring-payment consent. Existing subscriptions retain their original terms. The selected plan's approved duration must be frozen before acceptance. Trial start uses the authoritative provider-confirmed trial-start timestamp; Checkout completion alone is insufficient. KEEL grants trial entitlements only after the required verified confirmation; a browser redirect does not confirm the setup. A legacy local signup trial is a separate access mechanism and does not establish recurring-payment setup or consent.

## 3. Recurring billing
If the selected plan auto-renews, the recurring amount **[[DYNAMIC_CHECKOUT_AMOUNT]]**, charged currency **[[DYNAMIC_CURRENCY]]**, cadence **[[DYNAMIC_INTERVAL]]** and renewal/start date **[[DYNAMIC_RENEWAL_DATE]]** must be shown. Amounts and applicable taxes must be clear at authorization. Changed commercial terms require the legally appropriate fresh presentation, notice or acceptance.

## 4. Limits and overages
Plans may have feature quotas and AI/Data Credits. The currently approved plan describes exhaustion behavior. Paid overages and Pay-As-You-Go are unavailable unless separately disclosed and operationally supported: **[[APPROVED_OVERAGE_BEHAVIOR]]**. Do not automatically charge for excess usage without explicit authority.

## 5. Plan changes
Upgrades, downgrades, proration, Custom Plan reviews and effective dates depend on **[[APPROVED_PLAN_CHANGE_POLICY]]** and the actual provider capabilities. A review-required offer cannot become active merely because a user accepts the quote.

## 6. Cancellation and trial end
Customers can request cancellation through **[[VERIFIED_IN_APP_CANCELLATION_PATH]]** or the original payment provider's portal/support. For Paddle sales, its buyer portal and terms govern the cancellation transaction. Paid cancellation prevents future renewal while preserving access through the current paid-period end. Public trial-cancellation cutoff instructions remain **[[APPROVED_TRIAL_CANCELLATION_INSTRUCTIONS]]**. No cancellation UI should claim completion until the server/provider confirms it.

## 7. Failed payments and recovery
Failed, pending or ambiguous payments do not grant new subscription rights. Retries, grace periods, recovery and suspension follow **[[APPROVED_DELINQUENCY_POLICY]]** and verified provider status. KEEL must not create duplicate charges as a recovery shortcut.

## 8. Refunds, records and contact
Refunds are separate from cancellation and follow the Refund Policy, original Merchant of Record and applicable law. KEEL retains an audit record of accepted order terms and confirmation. Billing contact: **keel.business.ai@gmail.com**. Approved version/effective date: **[[SUBSCRIPTION_POLICY_APPROVAL_METADATA]]**.


---
