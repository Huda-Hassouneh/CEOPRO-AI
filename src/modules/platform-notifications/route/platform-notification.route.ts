import { Router } from "express";
import { requirePlatformPermission } from "../../../middleware/validators/validatePlatformUser.js";
import { platformNotificationController } from "../controller/platform-notification.controller.js";

const router = Router();
const readNotifications = requirePlatformPermission("notifications.read");

/*
 * Mount this router INSIDE the existing /platform-admin router after:
 *
 *   router.use(authenticateUser, requireTenant, requirePlatformRole)
 *
 * requirePlatformPermission() still re-checks the canonical platform boundary,
 * so each endpoint remains permission-gated by notifications.read.
 */
router.get(
  "/notifications",
  readNotifications,
  platformNotificationController.listNotifications
);

router.get(
  "/notifications/unread-count",
  readNotifications,
  platformNotificationController.getUnreadCount
);

router.post(
  "/notifications/read-all",
  readNotifications,
  platformNotificationController.markAllRead
);

router.post(
  "/notifications/:id/read",
  readNotifications,
  platformNotificationController.markRead
);

router.post(
  "/notifications/:id/archive",
  readNotifications,
  platformNotificationController.archive
);

export default router;
