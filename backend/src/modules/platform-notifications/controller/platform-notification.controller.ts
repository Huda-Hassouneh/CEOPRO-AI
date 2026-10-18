import type { Response } from "express";
import { z } from "zod";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import type { AppRequest } from "../../../types/request.js";
import { successResponse } from "../../../types/response.js";
import { sendApiError } from "../../../utils/http.js";
import { platformNotificationService } from "../service/platform-notification.service.js";

const DEFAULT_LIMIT = 20;

const listQuerySchema = z
  .object({
    limit: z
      .string()
      .regex(/^\d+$/)
      .transform(Number)
      .pipe(z.number().int().min(1).max(100))
      .optional(),
    cursor: z.uuid().optional(),
    unreadOnly: z
      .enum(["true", "false"])
      .transform((value) => value === "true")
      .optional(),
    includeArchived: z
      .enum(["true", "false"])
      .transform((value) => value === "true")
      .optional()
  })
  .strict();

const notificationIdSchema = z.uuid();

function identity(req: AppRequest) {
  if (!req.tenant_id || !req.user?.id) {
    return null;
  }

  return {
    platformTenantId: req.tenant_id,
    recipientUserId: req.user.id
  };
}

async function listNotifications(req: AppRequest, res: Response): Promise<void> {
  const actor = identity(req);
  if (!actor) {
    sendApiError(res, ERROR_CODES.FORBIDDEN);
    return;
  }

  const parsed = listQuerySchema.safeParse(req.query);
  if (!parsed.success) {
    sendApiError(res, ERROR_CODES.VALIDATION_ERROR, {
      details: parsed.error.flatten()
    });
    return;
  }

  try {
    const result = await platformNotificationService.listNotifications({
      ...actor,
      limit: parsed.data.limit ?? DEFAULT_LIMIT,
      cursor: parsed.data.cursor,
      unreadOnly: parsed.data.unreadOnly ?? false,
      includeArchived: parsed.data.includeArchived ?? false
    });

    res
      .status(200)
      .json(successResponse(result, "Platform notifications retrieved successfully"));
  } catch (error) {
    console.error("[PlatformNotifications] Failed to list notifications", error);
    sendApiError(res, ERROR_CODES.INTERNAL_SERVER_ERROR);
  }
}

async function getUnreadCount(req: AppRequest, res: Response): Promise<void> {
  const actor = identity(req);
  if (!actor) {
    sendApiError(res, ERROR_CODES.FORBIDDEN);
    return;
  }

  try {
    const unreadCount = await platformNotificationService.getUnreadCount(actor);

    res.status(200).json(
      successResponse(
        { unreadCount },
        "Unread notification count retrieved successfully"
      )
    );
  } catch (error) {
    console.error("[PlatformNotifications] Failed to get unread count", error);
    sendApiError(res, ERROR_CODES.INTERNAL_SERVER_ERROR);
  }
}

async function markRead(req: AppRequest, res: Response): Promise<void> {
  const actor = identity(req);
  if (!actor) {
    sendApiError(res, ERROR_CODES.FORBIDDEN);
    return;
  }

  const parsedId = notificationIdSchema.safeParse(req.params.id);
  if (!parsedId.success) {
    sendApiError(res, ERROR_CODES.VALIDATION_ERROR, {
      details: parsedId.error.flatten()
    });
    return;
  }

  try {
    const result = await platformNotificationService.markRead({
      ...actor,
      notificationId: parsedId.data
    });

    if (!result) {
      sendApiError(res, ERROR_CODES.RESOURCE_NOT_FOUND, {
        publicMessage: "Notification was not found."
      });
      return;
    }

    res
      .status(200)
      .json(successResponse(result, "Notification marked as read"));
  } catch (error) {
    console.error(
      "[PlatformNotifications] Failed to mark notification read",
      error
    );
    sendApiError(res, ERROR_CODES.INTERNAL_SERVER_ERROR);
  }
}

async function archive(req: AppRequest, res: Response): Promise<void> {
  const actor = identity(req);
  if (!actor) {
    sendApiError(res, ERROR_CODES.FORBIDDEN);
    return;
  }

  const parsedId = notificationIdSchema.safeParse(req.params.id);
  if (!parsedId.success) {
    sendApiError(res, ERROR_CODES.VALIDATION_ERROR, {
      details: parsedId.error.flatten()
    });
    return;
  }

  try {
    const result = await platformNotificationService.archive({
      ...actor,
      notificationId: parsedId.data
    });

    if (!result) {
      sendApiError(res, ERROR_CODES.RESOURCE_NOT_FOUND, {
        publicMessage: "Notification was not found."
      });
      return;
    }

    res
      .status(200)
      .json(successResponse(result, "Notification archived successfully"));
  } catch (error) {
    console.error("[PlatformNotifications] Failed to archive notification", error);
    sendApiError(res, ERROR_CODES.INTERNAL_SERVER_ERROR);
  }
}

async function markAllRead(req: AppRequest, res: Response): Promise<void> {
  const actor = identity(req);
  if (!actor) {
    sendApiError(res, ERROR_CODES.FORBIDDEN);
    return;
  }

  try {
    const updatedCount = await platformNotificationService.markAllRead(actor);

    res.status(200).json(
      successResponse(
        { updatedCount },
        "Notifications marked as read successfully"
      )
    );
  } catch (error) {
    console.error(
      "[PlatformNotifications] Failed to mark all notifications read",
      error
    );
    sendApiError(res, ERROR_CODES.INTERNAL_SERVER_ERROR);
  }
}

export const platformNotificationController = {
  listNotifications,
  getUnreadCount,
  markRead,
  archive,
  markAllRead
};
