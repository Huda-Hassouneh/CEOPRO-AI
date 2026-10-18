import { z } from "zod";

export const forecastGenerationBodySchema = z.object({
  horizon_days: z.number().int().min(1).max(60).default(7)
});
