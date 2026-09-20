import jwt from "jsonwebtoken";
import bcrypt from "bcrypt";
import { Request } from "express";

/**
 * Ensure necessary environment variables are set before accessing exports.
 */
if (!process.env.JWT_SECRET) {
  throw new Error("JWT_SECRET environment variable is not defined");
}

if (!process.env.JWT_REFRESH_SECRET) {
  console.warn(
    "JWT_REFRESH_SECRET is not defined. Using JWT_SECRET as a fallback. Please set this in production."
  );
}

const accessSecret = process.env.JWT_SECRET;
const refreshSecret = process.env.JWT_REFRESH_SECRET || accessSecret;
const HASH_SALTS = 12;

/**
 * Payload that you want to put inside the JWT.
 * Keys align exactly with your existing middleware checks.
 */
export interface TokenPayload {
  id: string;
  tenant_id?: string;
  email: string;
}

/**
 * Generate a short-lived Access JWT token.
 * Defaults to 1 hour expiration if JWT_ACCESS_EXPIRES_IN is not set.
 */
export function generateAccessToken(
  payload: TokenPayload,
  expiresIn: jwt.SignOptions["expiresIn"] = (process.env
    .JWT_ACCESS_EXPIRES_IN as jwt.SignOptions["expiresIn"]) || "1h"
): string {
  return jwt.sign(payload, accessSecret, { expiresIn });
}

/**
 * Generate a long-lived Refresh JWT token.
 * Defaults to 7 days expiration if JWT_REFRESH_EXPIRES_IN is not set.
 */
export function generateRefreshToken(
  payload: TokenPayload,
  expiresIn: jwt.SignOptions["expiresIn"] = (process.env
    .JWT_REFRESH_EXPIRES_IN as jwt.SignOptions["expiresIn"]) || "7d"
): string {
  return jwt.sign(payload, refreshSecret, { expiresIn });
}

/**
 * Check whether a JWT is valid.
 *
 * @param token The JWT string.
 * @param isRefresh Set to true if verifying a refresh token (uses the refresh secret).
 * @returns true if the token is correctly signed, not expired, and structurally valid.
 */
export function isTokenValid(
  token: string,
  isRefresh: boolean = false
): boolean {
  try {
    const secretToUse = isRefresh ? refreshSecret : accessSecret;
    jwt.verify(token, secretToUse);
    return true;
  } catch (err) {
    return false;
  }
}

/**
 * Get the payload from a valid JWT.
 *
 * @param token The JWT string.
 * @param isRefresh Set to true if decoding a refresh token.
 * @returns TokenPayload or null if the token is invalid or expired.
 */
export function getTokenPayload(
  token: string,
  isRefresh: boolean = false
): TokenPayload | null {
  try {
    const secretToUse = isRefresh ? refreshSecret : accessSecret;
    const payload = jwt.verify(token, secretToUse);

    if (typeof payload === "string") {
      return null;
    }

    return payload as TokenPayload;
  } catch {
    return null;
  }
}

/**
 * Helper function to extract a Bearer token from an Express Request object.
 */
export function extractTokenFromRequest(req: Request): string | null {
  const authHeader = req.headers.authorization;
  if (authHeader && authHeader.startsWith("Bearer ")) {
    return authHeader.split(" ")[1];
  }
  return null;
}

/**
 * Hash a password using bcrypt.
 */
export async function hashPassword(password: string): Promise<string> {
  return bcrypt.hash(password, HASH_SALTS);
}

/**
 * Compare a plain password against its bcrypt hash.
 */
export async function verifyPassword(
  password: string,
  passwordHash: string
): Promise<boolean> {
  return bcrypt.compare(password, passwordHash);
}
