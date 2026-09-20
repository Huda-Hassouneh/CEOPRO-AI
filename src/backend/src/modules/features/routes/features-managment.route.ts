import { Router } from "express";
import { featureController } from "../controller/features-managment.controller.js";
import { validateParams } from "../../../validators/validateParams.js";
import { validateBody } from "../../../validators/validateBody.js";
import {
  createFeatureSchema,
  featureIdParamSchema,
  updateFeatureSchema
} from "../../../DTO/features.dto.js";

// Import your security middlewares
import {
  authenticateUser,
  requireTenant,
  requirePermission
} from "../../../validators/validateUser.js";

const router = Router();

// 1. Authenticate and attach tenant context to ALL routes in this file
router.use(authenticateUser);
router.use(requireTenant);

// GET /features
// Protected endpoint: Get all system features
router.get("/", requirePermission("manage_catalog"), featureController.getAll);

// GET /features/:id
// Protected endpoint: Get a specific feature by ID
router.get(
  "/:id",
  requirePermission("manage_catalog"),
  validateParams(featureIdParamSchema),
  featureController.getOne
);

// POST /features
// Protected endpoint: Create a new system feature
router.post(
  "/",
  requirePermission("manage_catalog"),
  validateBody(createFeatureSchema),
  featureController.create
);

// PATCH /features/:id
// Protected endpoint: Update a system feature
router.patch(
  "/:id",
  requirePermission("manage_catalog"),
  validateParams(featureIdParamSchema),
  validateBody(updateFeatureSchema),
  featureController.update
);

export default router;
