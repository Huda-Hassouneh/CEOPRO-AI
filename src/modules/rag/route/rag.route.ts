import { Router } from "express";
import multer from "multer";
import { requireEntitlement, requireFeatureAccess } from "../../../validators/validateFeatures.js";
import { validateQuery } from "../../../validators/validateQuery.js";
import { authenticateUser, requireTenant } from "../../../validators/validateUser.js";
import { ragController } from "../controller/rag.controller.js";
import {
  ragDocumentsListQuerySchema,
  ragQuerySchema
} from "../types/rag.types.js";

const router = Router();

const upload = multer({
  storage: multer.memoryStorage(),
  limits: {
    fileSize: Number(process.env.MAX_UPLOAD_BYTES || 10 * 1024 * 1024),
    files: 1
  }
});

router.use(authenticateUser, requireTenant);

router.get(
  "/documents",
  validateQuery(ragDocumentsListQuerySchema),
  requireEntitlement("document_extraction"),
  ragController.listDocuments
);

router.post(
  "/documents",
  requireEntitlement("document_extraction"),
  upload.single("file"),
  ragController.uploadDocument
);

router.get(
  "/chunks/:chunk_id",
  requireFeatureAccess("rag_assistant"),
  ragController.getChunk
);

router.post(
  "/query",
  validateQuery(ragQuerySchema),
  requireEntitlement("rag_assistant"),
  ragController.queryAssistant
);

export default router;
