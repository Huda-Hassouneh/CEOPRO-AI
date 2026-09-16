import { Response } from "express";
import { webhookService } from "./webhook.service.js";

export async function webhookHandler(req: any, resp: Response) {
  const result = await webhookService(req.stripeEvent);
  resp.json(200);
}
