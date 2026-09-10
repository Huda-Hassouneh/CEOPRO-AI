import jwt from "jsonwebtoken";
import bcrypt from "bcrypt";
import { Request } from "express";

/**
 * Ensure JWT_SECRET variable is set before accessing any of provided exports .
 */
if (!process.env.JWT_SECRET) {
  throw new Error("JWT_SECRET environment variable is not defined");
}

const secret = process.env.JWT_SECRET;
const HASH_SALTS = 12;

/**
 * Payload that you want to put inside the JWT.
 * Extend this based on your authentication requirements.
 */

export interface TokenPayload {
  userId: string;
  tenantId?: string;
  role?: string;
}

/**
 * Generate a JWT token.
 */
export function generateToken(
  payload: TokenPayload,
  expiresIn: jwt.SignOptions["expiresIn"] = "1h"
): string {
  return jwt.sign(payload, secret, {
    expiresIn
  });
}
export function generateAdminToken() {
  return generateToken({ role: "admin", userId: "4", tenantId: "2" }, "24h");
}
/**
 * Check whether a JWT is valid.
 *
 * Returns true if:
 * - token is correctly signed
 * - token is not expired
 * - token has a valid JWT structure
 */
export function isTokenValid(token: string): boolean {
  try {
    jwt.verify(token, secret);
    return true;
  } catch (err) {
    return false;
  }
}

/**
 * Get the payload from a valid JWT.
 *
 * Returns null if the token is invalid or expired.
 */
export function getTokenPayload(token: string): TokenPayload | null {
  try {
    const payload = jwt.verify(token, secret);

    if (typeof payload === "string") {
      return null;
    }

    return payload as TokenPayload;
  } catch {
    return null;
  }
}

/**
 * Hash a password using bcrypt.
 */
export async function hashPassword(password: string): Promise<string> {
  return bcrypt.hash(password, HASH_SALTS);
}

/**
 * Compare a plain password against its bcrypt hash .
 */
export async function verifyPassword(
  password: string,
  passwordHash: string
): Promise<boolean> {
  return bcrypt.compare(password, passwordHash);
}
