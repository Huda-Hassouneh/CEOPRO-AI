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
import { authenticateUser } from "../../../validators/validateUser.js";
import {
  requirePlatformPermission,
  requirePlatformRole
} from "../../../validators/validatePlatformUser.js";

const router = Router();

// 1. Authenticate and attach tenant context to ALL routes in this file
router.use(authenticateUser);
router.use(requirePlatformRole);

// GET /features
// Protected endpoint: Get all system features
router.get(
  "/",
  requirePlatformPermission("billing.read"),
  featureController.getAll
);

// GET /features/:id
// Protected endpoint: Get a specific feature by ID
router.get(
  "/:id",
  requirePlatformPermission("billing.read"),
  validateParams(featureIdParamSchema),
  featureController.getOne
);

// POST /features
// Protected endpoint: Create a new system feature
router.post(
  "/",
  requirePlatformPermission("billing.manage"),
  validateBody(createFeatureSchema),
  featureController.create
);

// PATCH /features/:id
// Protected endpoint: Update a system feature
router.patch(
  "/:id",
  requirePlatformPermission("billing.manage"),
  validateParams(featureIdParamSchema),
  validateBody(updateFeatureSchema),
  featureController.update
);

export default router;
