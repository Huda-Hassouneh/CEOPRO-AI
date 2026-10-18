import { PrismaClient } from "../generated/prisma/client.js";
import { PrismaPg } from "@prisma/adapter-pg";
import { getRequiredEnv } from "./env.js";

const adapter = new PrismaPg({
  connectionString: getRequiredEnv("DATABASE_URL")
});

export const prisma = new PrismaClient({
  adapter
});
