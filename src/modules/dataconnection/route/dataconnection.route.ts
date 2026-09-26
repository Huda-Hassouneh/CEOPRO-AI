import { Router } from "express";
import * as dataConnectionsController from "../controller/dataconnection.controller.js";
import {
  authenticateUser,
  requireTenant
} from "../../../validators/validateUser.js";
import validateFile from "../../../validators/validateFile.js";
import { requireEntitlement } from "../../../validators/validateFeatures.js";
import multer from "multer";
import { extractionController } from "../../features/controller/features.controller.js";

const router = Router({ mergeParams: true });
router.use(authenticateUser, requireTenant);
const upload = multer({
  storage: multer.memoryStorage(),
  limits: {
    fileSize: Number(process.env.MAX_UPLOAD_BYTES || 10 * 1024 * 1024),
    files: 1
  }
});
// GET /companies/:companyId/data-connections
router.get("/", dataConnectionsController.getConnectionsOverview);
router.post(
  "/",
  // validateFile,
  requireEntitlement("document_extraction"),
  upload.single("file"), // Middleware to parse multipart/form-data
  extractionController.uploadFile
);

export default router;
