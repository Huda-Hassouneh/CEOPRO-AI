import { Response } from "express";
import { getTenantInvoicesService } from "../service/invoice.service.js";
import { ERROR_DEFINITIONS } from "../../../errors/error-definitions.js";
import { ERROR_CODES } from "../../../errors/error-codes.js";

export async function getInvoicesHandler(req: any, resp: Response) {
  try {
    const tenantId = req.tenant_id;

    if (!tenantId) {
      const def = ERROR_DEFINITIONS[ERROR_CODES.UNAUTHORIZED];
      return resp.status(def.statusCode).json({
        success: false,
        error: {
          code: ERROR_CODES.UNAUTHORIZED,
          message: "Tenant ID is missing.",
          statusCode: def.statusCode
        }
      });
    }

    const result = await getTenantInvoicesService(tenantId);

    if (!result.success) {
      const code = result.code as keyof typeof ERROR_CODES;
      const def =
        ERROR_DEFINITIONS[code] ||
        ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];

      return resp.status(def.statusCode).json({
        success: false,
        error: {
          code: code,
          message: result.message || def.message,
          statusCode: def.statusCode
        }
      });
    }

    return resp.status(200).json({
      success: true,
      message: "Invoices retrieved successfully",
      data: result.data
    });
  } catch (error) {
    console.error("[getInvoicesHandler Error]:", error);

    const def = ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];
    return resp.status(def.statusCode).json({
      success: false,
      error: {
        code: ERROR_CODES.INTERNAL_SERVER_ERROR,
        message: def.message,
        statusCode: def.statusCode
      }
    });
  }
}
