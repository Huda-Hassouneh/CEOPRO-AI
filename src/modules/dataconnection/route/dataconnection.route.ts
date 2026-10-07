import { Router } from "express";
import multer from "multer";
import { dataConnectionController } from "../controller/dataconnection.controller.js";
import {
  authenticateUser,
  requireTenant
} from "../../../middleware/validators/validateUser.js";
import { requireEntitlement } from "../../../middleware/validators/validateFeatures.js";
import validateFile from "../../../middleware/validators/validateFile.js";
import { MAX_UPLOAD_SIZE_BYTES } from "../types/dataconnection.validation.js";

const router = Router({ mergeParams: true });
router.use(authenticateUser, requireTenant);
const upload = multer({
  storage: multer.memoryStorage(),
  limits: {
    fileSize: MAX_UPLOAD_SIZE_BYTES,
    files: 1
  }
});
// route
router.post(
  "/sources",
  requireEntitlement("data_integration"),
  dataConnectionController.createSource
);
// GET /companies/:companyId/data-connections
router.get("/", dataConnectionController.getConnectionsOverview);
// POST /companies/:companyId/data-connections
router.post(
  "/",
  requireEntitlement("document_extraction"),
  upload.single("file"),
  validateFile,
  dataConnectionController.uploadFile
);

export default router;
