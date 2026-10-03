import { PrismaClient } from "../generated/prisma/client.js";
import { PrismaPg } from "@prisma/adapter-pg";
import { getRequiredEnv } from "./env.js";

const adapter = new PrismaPg({
  connectionString: getRequiredEnv("NOTIFICATION_WORKER_DATABASE_URL")
});

export const notificationWorkerPrisma = new PrismaClient({
  adapter
});
