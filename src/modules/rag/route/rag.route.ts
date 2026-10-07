import { Router } from "express";
import multer from "multer";
import {
  requireEntitlement,
  requireFeatureAccess
} from "../../../middleware/validators/validateFeatures.js";
import { validateQuery } from "../../../middleware/validators/validateQuery.js";
import {
  authenticateUser,
  requireTenant
} from "../../../middleware/validators/validateUser.js";
import { ragController } from "../controller/rag.controller.js";
import {
  ragDocumentsListQuerySchema,
  ragQuerySchema,
  MAX_RAG_DOCUMENT_SIZE_BYTES
} from "../types/rag.types.js";

const router = Router();

const upload = multer({
  storage: multer.memoryStorage(),
  limits: {
    fileSize: MAX_RAG_DOCUMENT_SIZE_BYTES,
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
