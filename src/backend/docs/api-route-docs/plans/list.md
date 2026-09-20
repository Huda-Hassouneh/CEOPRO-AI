# List Subscription Plans

## 1. Endpoint Details

`GET /subscription/plans`

## 2. Mental Model

Returns active catalog plans in ascending price order, enriched with billing options and feature entitlements for pricing-page and plan-selection workflows.

## 3. Technical Decisions

This public read route does not authenticate. The controller uses a dedicated query that filters `isActive`, includes plan-feature/feature relations, computes discounted totals and monthly equivalents, and reshapes feature data into a code-keyed object. It avoids exposing inactive catalog entries.

## 4. Inputs

- Headers: none required.
- Path/query/body: none.

## 5. Outputs

### Success

`200 OK`

```json
{
  "success": true,
  "message": "Plans retrieved successfully",
  "data": [
    {
      "id": "<uuid>",
      "name": "Pro",
      "tier_level": 2,
      "basePrice": 99,
      "currency": "USD",
      "pricingOptions": [
        {
          "period": "monthly",
          "months": 1,
          "discountPercent": 0,
          "totalPrice": 99,
          "monthlyEquivalent": 99,
          "stripePriceId": "price_..."
        }
      ],
      "features": { "ai_pricing": { "limitValue": 100, "type": "limit" } }
    }
  ]
}
```

### Errors

`500 Internal Server Error`:

```json
{
  "success": false,
  "message": "An internal server error occurred while retrieving plans",
  "data": []
}
```
