# Custom Plan Configurator

## Endpoint
`GET /subscription/custom-plans/configurator`

## Authorization
Authenticated user + active tenant membership.

## Response
Returns customer-safe configuration metadata only: pricing currency, billing options, trial period, and configurable feature definitions with localized names/descriptions/units plus server-defined `min`, `max`, and `step` for limit features.

Internal vendor costs, margins, infrastructure allocation, and pricing floors are not returned.
