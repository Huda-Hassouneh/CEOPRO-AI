import { Request, Response } from "express";
import { onBoardingService } from "../service/service.js";

export async function onBoardingHandler(req: Request, resp: Response) {
  const result = await onBoardingService();

  if (!result.success) {
    resp.status(result.error.statusCode).json(result);
  }
  resp.status(201).json(result);
}
