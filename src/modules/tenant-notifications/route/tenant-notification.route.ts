import { Router } from "express";
import {
  authenticateUser,
  requireTenant
} from "../../../middleware/validators/validateUser.js";
import { tenantNotificationController } from "../controller/tenant-notification.controller.js";

const router = Router();

router.use(authenticateUser, requireTenant);

router.get("/", tenantNotificationController.listNotifications);
router.get("/unread-count", tenantNotificationController.getUnreadCount);
router.post("/read-all", tenantNotificationController.markAllRead);
router.post("/:id/read", tenantNotificationController.markRead);
router.post("/:id/archive", tenantNotificationController.archive);

export default router;
