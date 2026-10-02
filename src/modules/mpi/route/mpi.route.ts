import { Router } from "express";
import { requireFeatureAccess } from "../../../validators/validateFeatures.js";
import {
  authenticateUser,
  requireTenant
} from "../../../validators/validateUser.js";
import { getSummary } from "../controller/mpi.controller.js";
import { validateMpiSummaryQuery } from "../types/mpi.validation.js";

const router = Router();

router.use(authenticateUser, requireTenant);

router.get(
  "/summary",
  validateMpiSummaryQuery,
  // requireFeatureAccess("market_perception"),
  getSummary
);

export default router;
