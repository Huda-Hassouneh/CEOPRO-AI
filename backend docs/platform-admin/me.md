# Platform Admin Principal

## Endpoint
`GET /platform-admin/me`

## Authorization
`authenticateUser` + `requireTenant` + `requirePlatformRole`. The active `TenantUser.roleKey` must be `owner`.

## Response
Returns the authenticated user's id/email/name plus:

```json
{
  "role": "owner",
  "roleKey": "owner",
  "permissions": { "billing.read": true },
  "status": "active"
}
```

The frontend platform-admin shell uses this response to mirror capabilities. It does not replace backend authorization.
