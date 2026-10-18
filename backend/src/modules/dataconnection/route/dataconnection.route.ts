import { Router } from "express";
import multer from "multer";
import { dataConnectionController } from "../controller/dataconnection.controller.js";
import {
  authenticateUser,
  requireTenant
} from "../../../middleware/validators/validateUser.js";
import { requireEntitlement } from "../../../middleware/validators/validateFeatures.js";
import { requireFeatureAccess } from "../../../middleware/validators/validateFeatures.js";
import validateFile from "../../../middleware/validators/validateFile.js";
import { MAX_UPLOAD_SIZE_BYTES } from "../types/dataconnection.validation.js";

import storeRoutes, {protectStoreLifecycle} from "../store/routes.js";

const router = Router({ mergeParams: true });
router.use(authenticateUser, requireTenant);
router.use("/store", storeRoutes);
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
router.patch(
  "/sources/:sourceId",
  protectStoreLifecycle,
  dataConnectionController.setSourceActive
);
router.delete(
  "/sources/:sourceId/connection",
  protectStoreLifecycle,
  dataConnectionController.disconnectSource
);
router.get(
  "/templates/sales/:format",
  requireEntitlement("document_extraction"),
  dataConnectionController.downloadSalesTemplate
);
router.get(
  "/templates/products.csv",
  requireFeatureAccess("document_extraction"),
  dataConnectionController.downloadProductReference
);
router.get(
  "/templates/catalog.csv",
  requireFeatureAccess("document_extraction"),
  dataConnectionController.downloadCatalogReference
);
router.get(
  "/templates/:kind/:format",
  requireEntitlement("document_extraction"),
  dataConnectionController.downloadStructuredTemplate
);
router.get(
  "/imports/products",
  requireFeatureAccess("document_extraction"),
  dataConnectionController.searchImportProducts
);
router.post(
  "/imports/:kind/preview",
  requireEntitlement("document_extraction"),
  upload.single("file"),
  dataConnectionController.previewStructuredBusinessFile
);
router.post(
  "/imports/:kind/previews/:draftId/confirm",
  requireEntitlement("document_extraction"),
  dataConnectionController.confirmStructuredBusinessFile
);
router.post(
  "/imports/:kind/previews/:draftId/review",
  requireEntitlement("document_extraction"),
  dataConnectionController.reviewStructuredBusinessFile
);
router.post(
  "/imports/:kind",
  requireEntitlement("document_extraction"),
  upload.single("file"),
  dataConnectionController.importStructuredBusinessFile
);
// GET /companies/:companyId/data-connections
router.get(
  "/",
  dataConnectionController.getConnectionsOverview
);
// POST /companies/:companyId/data-connections
router.post(
  "/",
  // New uploads reserve quota atomically in the service/repository. An exact
  // previously charged CSV recovery does not consume that quota a second time.
  requireFeatureAccess("document_extraction"),
  upload.single("file"),
  validateFile,
  dataConnectionController.uploadFile
);
router.get(
  "/jobs",
  dataConnectionController.listIngestionJobs
);
router.get(
  "/jobs/:jobId/staging",
  dataConnectionController.getIngestionStagingRows
);
router.patch(
  "/jobs/:jobId/staging/:rowId",
  requireEntitlement("document_extraction"),
  dataConnectionController.updateIngestionStagingRow
);
router.get(
  "/jobs/:jobId",
  dataConnectionController.getIngestionJob
);
router.post(
  "/jobs/:jobId/retry",
  requireEntitlement("document_extraction"),
  dataConnectionController.retryIngestionJob
);

export default router;
