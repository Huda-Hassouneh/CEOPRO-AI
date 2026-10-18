import path from "node:path";
import dotenv from "dotenv";

const envPath = process.env.DOTENV_CONFIG_PATH
  ? path.resolve(process.env.DOTENV_CONFIG_PATH)
  : path.resolve(process.cwd(), ".env");

dotenv.config({ path: envPath });

export function getRequiredEnv(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`${name} environment variable is required`);
  }
  return value;
}

export function getCorsOrigins(): string[] {
  const raw = process.env.CORS_ORIGINS ?? "http://localhost:5173";
  return raw
    .split(",")
    .map((origin) => origin.trim())
    .filter(Boolean);
}
