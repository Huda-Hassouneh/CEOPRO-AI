import { Router } from "express";
import * as dataConnectionsController from "../controller/dataconnection.controller.js";
import {
  authenticateUser,
  requireTenant
} from "../../../validators/validateUser.js";

const router = Router({ mergeParams: true });
router.use(authenticateUser, requireTenant);

// GET /companies/:companyId/data-connections
router.get("/", dataConnectionsController.getConnectionsOverview);

export default router;
