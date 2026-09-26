import { Router } from "express";
import * as leaderboardController from "./controller.js";
import {
  authenticateUser,
  requireTenant
} from "../../validators/validateUser.js";

const router = Router({ mergeParams: true });

router.use(authenticateUser, requireTenant);

// GET /companies/:companyId/leaderboard/competitors
router.get("/", leaderboardController.getLeaderboard);

export default router;
