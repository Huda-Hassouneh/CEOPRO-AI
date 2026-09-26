import { Request, Response, NextFunction } from "express";
import * as competitorsService from "./service.js";

export const listCompetitors = async (
  req: any,
  res: Response,
  next: NextFunction
) => {
  try {
    const tenantId = req.tenant_id;
    const data = await competitorsService.getCompetitorsList(tenantId);
    return res.status(200).json({ status: "success", data });
  } catch (error) {
    next(error);
  }
};

export const getCompetitorProfile = async (
  req: any,
  res: Response,
  next: NextFunction
) => {
  try {
    const tenantId = req.tenant_id;
    const competitorId = req.params.competitorId;
    const data = await competitorsService.getCompetitorProfile(
      tenantId,
      competitorId
    );
    return res.status(200).json({ status: "success", data });
  } catch (error) {
    next(error);
  }
};

export const createCompetitor = async (
  req: any,
  res: Response,
  next: NextFunction
) => {
  try {
    const tenantId = req.tenant_id;
    const data = await competitorsService.createCompetitor(tenantId, req.body);
    return res.status(201).json({ status: "success", data });
  } catch (error) {
    next(error);
  }
};
