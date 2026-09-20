import { generateAccessToken } from "../utils/token.js";

const ADMIN_PAYLOAD = {
  id: "f47ac10b-58cc-4372-a567-0e02b2c3d479", // Matches users.id
  tenant_id: "550e8400-e29b-41d4-a716-446655440000", // Matches companies.id
  email: "admin@test.com",
  role: "admin"
};

// Use it like this to print your token when the server starts:
// import { generateAccessToken } from "./utils/token.js";

console.log("=== USE THIS TOKEN IN POSTMAN ===");
console.log(generateAccessToken(ADMIN_PAYLOAD));
console.log("=================================");
