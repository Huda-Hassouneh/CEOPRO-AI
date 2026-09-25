import jwt from "jsonwebtoken";
import bcrypt from "bcrypt";
import type { Request } from "express";

const HASH_SALTS = 12;
const JWT_ALGORITHMS: jwt.Algorithm[] = ["HS256"];

function getSecret(isRefresh: boolean): string {
  const key = isRefresh ? "JWT_REFRESH_SECRET" : "JWT_SECRET";
  const secret = process.env[key]?.trim();
  if (!secret) throw new Error(`${key} environment variable is not defined`);
  return secret;
}

export interface TokenPayload {
  id: string;
  tenant_id?: string;
  email: string;
  roleKey: string;
}

export function generateAccessToken(
  payload: TokenPayload,
  expiresIn: jwt.SignOptions["expiresIn"] = (process.env
    .JWT_ACCESS_EXPIRES_IN as jwt.SignOptions["expiresIn"]) || "1h",
): string {
  return jwt.sign(payload, getSecret(false), { algorithm: "HS256", expiresIn });
}

export function generateRefreshToken(
  payload: TokenPayload,
  expiresIn: jwt.SignOptions["expiresIn"] = (process.env
    .JWT_REFRESH_EXPIRES_IN as jwt.SignOptions["expiresIn"]) || "7d",
): string {
  return jwt.sign(payload, getSecret(true), { algorithm: "HS256", expiresIn });
}

export function isTokenValid(token: string, isRefresh = false): boolean {
  try {
    jwt.verify(token, getSecret(isRefresh), { algorithms: JWT_ALGORITHMS });
    return true;
  } catch {
    return false;
  }
}

export function getTokenPayload(
  token: string,
  isRefresh = false,
): TokenPayload | null {
  try {
    const payload = jwt.verify(token, getSecret(isRefresh), {
      algorithms: JWT_ALGORITHMS,
    });
    if (
      typeof payload === "string" ||
      typeof payload.id !== "string" ||
      typeof payload.email !== "string" ||
      typeof payload.roleKey !== "string"
    ) {
      return null;
    }
    return payload as TokenPayload;
  } catch {
    return null;
  }
}

export function extractTokenFromRequest(req: Request): string | null {
  const match = req.headers.authorization?.match(/^Bearer\s+(\S+)$/i);
  return match?.[1] ?? null;
}

export async function hashPassword(password: string): Promise<string> {
  return bcrypt.hash(password, HASH_SALTS);
}

export async function verifyPassword(
  password: string,
  passwordHash: string,
): Promise<boolean> {
  return bcrypt.compare(password, passwordHash);
}
