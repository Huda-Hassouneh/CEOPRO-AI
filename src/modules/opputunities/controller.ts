import { Request, Response, NextFunction } from "express";
import * as leaderboardService from "./service.js";

export const getLeaderboard = async (
  req: any,
  res: Response,
  next: NextFunction
) => {
  try {
    const tenantId = req.tenant_id;
    const data = await leaderboardService.getCompetitorLeaderboard(tenantId);
    return res.status(200).json({ status: "success", data });
  } catch (error) {
    next(error);
  }
};
