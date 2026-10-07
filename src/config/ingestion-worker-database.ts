import { PrismaPg } from "@prisma/adapter-pg";
import { PrismaClient } from "../generated/prisma/client.js";
import { getRequiredEnv } from "./env.js";

const adapter = new PrismaPg({
  connectionString: getRequiredEnv("INGESTION_WORKER_DATABASE_URL")
});

/** Dedicated database identity; it must not reuse DATABASE_URL or the notification role. */
export const ingestionWorkerPrisma = new PrismaClient({ adapter });
