import { Router } from "express";
import * as competitorsController from "./controller.js";
import {
  authenticateUser,
  requireTenant
} from "../../validators/validateUser.js";

const router = Router({ mergeParams: true });

router.use(authenticateUser, requireTenant);

// GET /companies/:companyId/competitors
router.get("/", competitorsController.listCompetitors);

// POST /companies/:companyId/competitors
router.post("/", competitorsController.createCompetitor);

// GET /companies/:companyId/competitors/:competitorId
router.get("/:competitorId", competitorsController.getCompetitorProfile);

export default router;
