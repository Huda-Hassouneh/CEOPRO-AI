import { generateAccessToken } from "../src/utils/token.js";

// Use IDs that actually exist in your local/shared database.
// Authorization is resolved from the TenantUser row for this user + tenant.
const OWNER_PAYLOAD = {
  id: process.env.DEV_OWNER_USER_ID ?? "9c64d665-7286-4d4f-928d-40e6d6a560aa",
  tenant_id: process.env.DEV_OWNER_TENANT_ID ?? "c3865d65-e03a-4f34-b917-9bb93e9cfc5b",
  email: process.env.DEV_OWNER_EMAIL ?? "owner@ceopro.ai",
  roleKey: "owner",
};

process.stdout.write(`${generateAccessToken(OWNER_PAYLOAD)}\n`);
