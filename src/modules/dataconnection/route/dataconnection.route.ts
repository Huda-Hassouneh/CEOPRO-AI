import { Router } from "express";
import multer from "multer";
import { dataConnectionController } from "../controller/dataconnection.controller.js";
import {
  authenticateUser,
  requireTenant
} from "../../../validators/validateUser.js";
import { requireEntitlement } from "../../../validators/validateFeatures.js";

const router = Router({ mergeParams: true });
router.use(authenticateUser, requireTenant);
const upload = multer({
  storage: multer.memoryStorage(),
  limits: {
    fileSize: Number(process.env.MAX_UPLOAD_BYTES || 10 * 1024 * 1024),
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
  dataConnectionController.uploadFile
);

export default router;
