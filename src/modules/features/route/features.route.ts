import { Router } from "express";
import multer from "multer";

import {
  requireEntitlement,
  requireFeatureAccess
} from "../../../validators/validateFeatures.js";
import {
  authenticateUser,
  requireTenant
} from "../../../validators/validateUser.js";
import { extractionPendingQuerySchema } from "../types/features.dto.js";
import { validateQuery } from "../../../validators/validateQuery.js";
import { extractionController } from "../controller/features.controller.js";

const router = Router();

const upload = multer({
  storage: multer.memoryStorage(),
  limits: {
    fileSize: Number(process.env.MAX_UPLOAD_BYTES || 10 * 1024 * 1024),
    files: 1
  }
});

router.use(authenticateUser);
router.use(requireTenant);

// RAG routes are now owned by src/modules/rag and mounted at /features/rag.
// Sentiment, MPI, pricing, forecasting, etc. remain owned by their modules.

router.post(
  "/extraction/upload",
  requireEntitlement("document_extraction"),
  upload.single("file"),
  extractionController.uploadFile
);

router.post(
  "/extraction/process-pending",
  validateQuery(extractionPendingQuerySchema),
  requireFeatureAccess("document_extraction"),
  extractionController.processPending
);

export default router;
