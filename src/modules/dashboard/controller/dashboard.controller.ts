import { Request, Response, NextFunction } from "express";
import * as dashboardService from "../service/dashboard.service.js";

export const getAggregate = async (
  req: Request,
  res: Response,
  next: NextFunction
) => {
  try {
    // Extract companyId from URL params (based on your frontend /companies/:companyId/dashboard route)
    const tenantId = req.params.companyId as string;

    // Extract and parse periodDays from query string, defaulting to 30
    const periodDays = req.query.periodDays
      ? parseInt(req.query.periodDays as string, 10)
      : 30;

    if (!tenantId) {
      return res.status(400).json({
        status: "error",
        message: "Company/Tenant ID is required"
      });
    }

    const data = await dashboardService.getDashboardAggregate(
      tenantId,
      periodDays
    );

    // Return standard success response shape expected by your frontend
    return res.status(200).json({
      status: "success",
      data: data
    });
  } catch (error) {
    next(error); // Pass to your global errorHandler middleware
  }
};
