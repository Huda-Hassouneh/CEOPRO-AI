import { Router } from "express";
import multer from "multer";

import {
  requireEntitlement,
  requireFeatureAccess
} from "../../../middleware/validators/validateFeatures.js";
import {
  authenticateUser,
  requireTenant
} from "../../../middleware/validators/validateUser.js";
import { extractionPendingQuerySchema } from "../types/features.dto.js";
import { validateQuery } from "../../../middleware/validators/validateQuery.js";
import validateFile from "../../../middleware/validators/validateFile.js";
import { extractionController } from "../controller/features.controller.js";
import { MAX_UPLOAD_SIZE_BYTES } from "../../dataconnection/types/dataconnection.validation.js";

const router = Router();

const upload = multer({
  storage: multer.memoryStorage(),
  limits: {
    fileSize: MAX_UPLOAD_SIZE_BYTES,
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
  validateFile,
  extractionController.uploadFile
);

router.post(
  "/extraction/process-pending",
  validateQuery(extractionPendingQuerySchema),
  requireFeatureAccess("document_extraction"),
  extractionController.processPending
);

export default router;
