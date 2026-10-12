import type { NextFunction, Response as ExpressResponse } from "express";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import { ERROR_CODES } from "../../../errors/error-codes.js";
import { ERROR_DEFINITIONS } from "../../../errors/error-definitions.js";
import type { AppRequest } from "../../../types/request.js";
import { errorResponse, successResponse } from "../../../types/response.js";

import {
  isDataConnectionServiceError,
  dataConnectionService
} from "../service/dataconnection.service.js";
import { createStructuredImportTemplate } from "../service/structured-business-import.js";
import { getStructuredImportProductReference, searchStructuredImportProducts } from "../repo/structured-business-import.repo.js";

import { isAiServiceError } from "../client/ingestion.client.js";

type ErrorCode = (typeof ERROR_CODES)[keyof typeof ERROR_CODES];

function sendError(
  res: ExpressResponse,
  code: ErrorCode,
  detail?: unknown
): void {
  const errDef = ERROR_DEFINITIONS[code];

  res
    .status(errDef.statusCode)
    .json(errorResponse(errDef.message, errDef.statusCode, code, detail));
}

function handleError(res: ExpressResponse, error: unknown): void {
  console.error("[DataConnectionController] Request failed", {
    name: error instanceof Error ? error.name : "UnknownError"
  });

  if (isDataConnectionServiceError(error)) {
    switch (error.code) {
      case "INVALID_FILE_UPLOAD":
        sendError(
          res,
          ERROR_CODES.INVALID_FILE_UPLOAD,
          error.detail ?? error.message
        );
        return;

      case "INVALID_PARAMETER":
        sendError(res, ERROR_CODES.INVALID_PARAMETER, error.detail ?? error.message);
        return;

      case "FILE_SIZE_LIMIT_EXCEEDED":
        sendError(
          res,
          ERROR_CODES.FILE_SIZE_LIMIT_EXCEEDED,
          error.detail ?? error.message
        );
        return;

      case "FEATURE_NOT_INCLUDED":
        sendError(res, ERROR_CODES.FORBIDDEN, error.detail ?? error.message);
        return;

      case "USAGE_EXCEEDED":
        sendError(
          res,
          ERROR_CODES.PAYMENT_REQUIRED,
          error.detail ?? {
            message: error.message
          }
        );
        return;
      case "DUPLICATE_RESOURCE":
        sendError(res, ERROR_CODES.RESOURCE_ALREADY_EXISTS, error.detail ?? error.message);
        return;
      case "SOURCE_RECONNECT_REQUIRED":
        sendError(
          res,
          ERROR_CODES.DATA_SOURCE_RECONNECT_REQUIRED,
          error.detail ?? error.message
        );
        return;
      case "RESOURCE_NOT_FOUND":
        sendError(res, ERROR_CODES.RESOURCE_NOT_FOUND, error.detail ?? error.message);
        return;
      case "JOB_NOT_RETRYABLE":
        sendError(res, ERROR_CODES.INVALID_PARAMETER, error.detail ?? error.message);
        return;
    }
  }

  if (isAiServiceError(error)) {
    sendError(res, ERROR_CODES.EXTERNAL_SERVICE_ERROR, {
      upstream_status: error.upstreamStatus ?? null
    });
    return;
  }

  sendError(res, ERROR_CODES.INTERNAL_SERVER_ERROR);
}

export const dataConnectionController = {
  downloadCatalogReference: async (req: AppRequest, res: ExpressResponse): Promise<void> => {
    try {
      if (!req.tenant_id || !req.user?.user_id) { sendError(res, ERROR_CODES.FORBIDDEN); return; }
      const products = await getStructuredImportProductReference(req.tenant_id, req.user.user_id);
      const csvCell = (value: string) => `"${(/^\s*[=+@\-]/.test(value) ? `'${value}` : value).replace(/"/g, '""')}"`;
      const rows = products.map((product) => {
        const names = product.product_name;
        const localized = (language: string) => names && typeof names === "object" && !Array.isArray(names)
          ? String((names as Record<string, unknown>)[language] ?? "") : typeof names === "string" ? names : "";
        return [product.sku ?? "", localized("en"), localized("ar"), product.currency].map(csvCell).join(",");
      });
      res.setHeader("Content-Type", "text/csv; charset=utf-8");
      res.setHeader("Content-Disposition", 'attachment; filename="ceopro_product_catalog.csv"');
      res.status(200).send(`\uFEFFsku,product_name_en,product_name_ar,currency\r\n${rows.join("\r\n")}${rows.length ? "\r\n" : ""}`);
    } catch (error) { handleError(res, error); }
  },
  searchImportProducts: async (req: AppRequest, res: ExpressResponse): Promise<void> => {
    try {
      if (!req.tenant_id || !req.user?.user_id) { sendError(res, ERROR_CODES.FORBIDDEN); return; }
      const query = typeof req.query.q === "string" ? req.query.q : "";
      if (query.length > 100) { sendError(res, ERROR_CODES.INVALID_PARAMETER); return; }
      const products = await searchStructuredImportProducts(req.tenant_id, req.user.user_id, query);
      res.status(200).json(successResponse(products, "Available products"));
    } catch (error) { handleError(res, error); }
  },
  previewStructuredBusinessFile: async (req: AppRequest, res: ExpressResponse): Promise<void> => {
    try {
      if (!req.tenant_id || !req.user?.user_id) { sendError(res, ERROR_CODES.FORBIDDEN); return; }
      if (!req.file) { sendError(res, ERROR_CODES.INVALID_FILE_UPLOAD, "A multipart file is required in field 'file'."); return; }
      const preview = await dataConnectionService.previewStructuredBusinessFile(
        { tenantId: req.tenant_id, userId: req.user.user_id, file: req.file },
        typeof req.params.kind === "string" ? req.params.kind : ""
      );
      res.status(200).json(successResponse(preview, "Import preview ready for review"));
    } catch (error) { handleError(res, error); }
  },
  reviewStructuredBusinessFile: async (req: AppRequest, res: ExpressResponse): Promise<void> => {
    try {
      if (!req.tenant_id || !req.user?.user_id) { sendError(res, ERROR_CODES.FORBIDDEN); return; }
      const review = await dataConnectionService.reviewStructuredBusinessFile({
        tenantId: req.tenant_id, userId: req.user.user_id,
        kind: typeof req.params.kind === "string" ? req.params.kind : "",
        draftId: typeof req.params.draftId === "string" ? req.params.draftId : "",
        choices: req.body?.choices ?? {}
      });
      res.status(200).json(successResponse(review, "Import changes ready for confirmation"));
    } catch (error) { handleError(res, error); }
  },
  confirmStructuredBusinessFile: async (req: AppRequest, res: ExpressResponse): Promise<void> => {
    try {
      if (!req.tenant_id || !req.user?.user_id) { sendError(res, ERROR_CODES.FORBIDDEN); return; }
      const result = await dataConnectionService.confirmStructuredBusinessFile({
        tenantId: req.tenant_id, userId: req.user.user_id,
        kind: typeof req.params.kind === "string" ? req.params.kind : "",
        draftId: typeof req.params.draftId === "string" ? req.params.draftId : "",
        choices: req.body?.choices ?? {}, reviewHash: req.body?.reviewHash
      });
      res.status(200).json(successResponse(result, "Business records committed"));
    } catch (error) { handleError(res, error); }
  },
  downloadProductReference: async (req: AppRequest, res: ExpressResponse): Promise<void> => {
    try {
      const tenantId = req.tenant_id;
      const userId = req.user?.user_id;
      if (!tenantId || !userId) {
        sendError(res, ERROR_CODES.FORBIDDEN);
        return;
      }
      const products = await getStructuredImportProductReference(tenantId, userId);
      const csvCell = (value: string) => {
        const safe = /^\s*[=+@\-]/.test(value) ? `'${value}` : value;
        return `"${safe.replace(/"/g, '""')}"`;
      };
      const csvName = (value: unknown, language: "en" | "ar") => {
        if (typeof value === "string") return value;
        if (value && typeof value === "object" && !Array.isArray(value)) {
          const name = (value as Record<string, unknown>)[language];
          return typeof name === "string" ? name : "";
        }
        return "";
      };
      const rows = products.map((product) => [
        product.product_id,
        product.sku ?? "",
        csvName(product.product_name, "en"),
        csvName(product.product_name, "ar"),
        product.currency
      ].map(csvCell).join(","));
      const content = ["product_id,sku,product_name_en,product_name_ar,currency", ...rows].join("\r\n") + "\r\n";
      res.setHeader("Content-Type", "text/csv; charset=utf-8");
      res.setHeader("Content-Disposition", 'attachment; filename="ceopro_product_ids.csv"');
      res.status(200).send(`\uFEFF${content}`);
    } catch (error) {
      handleError(res, error);
    }
  },
  downloadStructuredTemplate: async (req: AppRequest, res: ExpressResponse): Promise<void> => {
    const { kind, format } = req.params;
    if ((kind !== "invoices" && kind !== "inventory") || (format !== "csv" && format !== "xlsx")) {
      sendError(res, ERROR_CODES.INVALID_PARAMETER, "Choose an invoice or inventory CSV/XLSX template.");
      return;
    }
    const content = createStructuredImportTemplate(kind, format);
    res.setHeader("Content-Type", format === "csv"
      ? "text/csv; charset=utf-8"
      : "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
    res.setHeader("Content-Disposition", `attachment; filename="ceopro_${kind}_import_v1.${format}"`);
    res.status(200).send(content);
  },

  importStructuredBusinessFile: async (req: AppRequest, res: ExpressResponse): Promise<void> => {
    try {
      const tenantId = req.tenant_id;
      const userId = req.user?.user_id;
      if (!tenantId || !userId) {
        sendError(res, ERROR_CODES.FORBIDDEN, "Authenticated tenant and user are required.");
        return;
      }
      if (!req.file) {
        sendError(res, ERROR_CODES.INVALID_FILE_UPLOAD, "A multipart file is required in field 'file'.");
        return;
      }
      const result = await dataConnectionService.importStructuredBusinessFile(
        { tenantId, userId, file: req.file },
        typeof req.params.kind === "string" ? req.params.kind : ""
      );
      res.status(200).json(successResponse(result, "Business records imported successfully"));
    } catch (error) {
      handleError(res, error);
    }
  },

  downloadSalesTemplate: async (
    req: AppRequest,
    res: ExpressResponse
  ): Promise<void> => {
    const format = typeof req.params.format === "string" ? req.params.format.toLowerCase() : "";
    if (format !== "csv" && format !== "xlsx") {
      sendError(res, ERROR_CODES.INVALID_PARAMETER, "Template format must be csv or xlsx.");
      return;
    }

    try {
      const filename = "ceopro_sales_transaction_import_v1." + format;
      const templateUrl = new URL("../templates/" + filename, import.meta.url);
      let content: Buffer;
      try {
        content = await readFile(templateUrl);
      } catch {
        content = await readFile(
          resolve(process.cwd(), "src/modules/dataconnection/templates", filename)
        );
      }
      res.setHeader(
        "Content-Type",
        format === "csv"
          ? "text/csv; charset=utf-8"
          : "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
      );
      res.setHeader("Content-Disposition", "attachment; filename=\"" + filename + "\"");
      res.status(200).send(content);
    } catch (error) {
      console.error("[DataConnectionController] Sales template unavailable", error);
      sendError(res, ERROR_CODES.INTERNAL_SERVER_ERROR);
    }
  },

  uploadFile: async (req: AppRequest, res: ExpressResponse): Promise<void> => {
    try {
      const tenantId = req.tenant_id;

      const userId = req.user?.user_id;

      if (typeof tenantId !== "string" || !tenantId.trim()) {
        sendError(
          res,
          ERROR_CODES.FORBIDDEN,
          "Tenant context is required for this operation."
        );
        return;
      }

      if (typeof userId !== "string" || !userId.trim()) {
        sendError(
          res,
          ERROR_CODES.FORBIDDEN,
          "Authenticated user context is required for this operation."
        );
        return;
      }

      if (!req.file) {
        sendError(
          res,
          ERROR_CODES.INVALID_FILE_UPLOAD,
          "A multipart file upload is required."
        );
        return;
      }

      const result = await dataConnectionService.uploadExtraction({
        tenantId,
        userId,
        file: req.file
      });

      res
        .status(200)
        .json(
          successResponse(result, "Document extracted and queued for import")
        );
    } catch (error) {
      handleError(res, error);
    }
  },

  processPending: async (
    _req: AppRequest,
    res: ExpressResponse
  ): Promise<void> => {
    sendError(
      res,
      ERROR_CODES.NOT_IMPLEMENTED,
      "Submit a file to extract it; the current AI service does not support pending batch processing."
    );
  },
  getConnectionsOverview: async (
    req: AppRequest,
    res: ExpressResponse,
    next: NextFunction
  ) => {
    try {
      const tenantId = req.tenant_id;
      if (typeof tenantId !== "string" || !tenantId.trim()) {
        sendError(res, ERROR_CODES.FORBIDDEN, "Tenant context is required.");
        return;
      }
      const userId = req.user?.user_id;
      if (typeof userId !== "string" || !userId.trim()) {
        sendError(res, ERROR_CODES.FORBIDDEN, "Authenticated user context is required.");
        return;
      }

      const data = await dataConnectionService.getDataConnectionsOverview(
        tenantId,
        userId
      );

      return res.status(200).json({
        status: "success",
        data
      });
    } catch (error) {
      next(error);
    }
  },

  listIngestionJobs: async (
    req: AppRequest,
    res: ExpressResponse
  ): Promise<void> => {
    const tenantId = req.tenant_id;
    const userId = req.user?.user_id;
    if (typeof tenantId !== "string" || !tenantId.trim() || !userId) {
      sendError(res, ERROR_CODES.FORBIDDEN, "Authenticated tenant context is required.");
      return;
    }
    try {
      const jobs = await dataConnectionService.listIngestionJobs(tenantId, userId);
      res.status(200).json(successResponse({ jobs }, "Ingestion jobs loaded"));
    } catch (error) {
      handleError(res, error);
    }
  },

  getIngestionJob: async (
    req: AppRequest,
    res: ExpressResponse
  ): Promise<void> => {
    const tenantId = req.tenant_id;
    const userId = req.user?.user_id;
    const jobId = req.params.jobId;
    if (typeof tenantId !== "string" || !tenantId.trim() || !userId) {
      sendError(res, ERROR_CODES.FORBIDDEN, "Authenticated tenant context is required.");
      return;
    }
    if (
      typeof jobId !== "string" ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(jobId)
    ) {
      sendError(res, ERROR_CODES.INVALID_PARAMETER, "jobId must be a UUID.");
      return;
    }
    try {
      const job = await dataConnectionService.getIngestionJob(
        tenantId,
        userId,
        jobId
      );
      res.status(200).json(successResponse(job, "Ingestion job loaded"));
    } catch (error) {
      handleError(res, error);
    }
  },

  getIngestionStagingRows: async (
    req: AppRequest,
    res: ExpressResponse
  ): Promise<void> => {
    const tenantId = req.tenant_id;
    const userId = req.user?.user_id;
    const jobId = req.params.jobId;
    const page = Number(req.query.page ?? 1);
    const pageSize = Number(req.query.pageSize ?? 50);
    if (typeof tenantId !== "string" || !tenantId.trim() || !userId) {
      sendError(res, ERROR_CODES.FORBIDDEN, "Authenticated tenant context is required.");
      return;
    }
    if (
      typeof jobId !== "string" ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(jobId)
    ) {
      sendError(res, ERROR_CODES.INVALID_PARAMETER, "jobId must be a UUID.");
      return;
    }
    if (
      !Number.isInteger(page) ||
      page < 1 ||
      !Number.isInteger(pageSize) ||
      pageSize < 1 ||
      pageSize > 100
    ) {
      sendError(res, ERROR_CODES.INVALID_PARAMETER, "page must be positive and pageSize must be between 1 and 100.");
      return;
    }
    try {
      const result = await dataConnectionService.getIngestionStagingRows(
        tenantId,
        userId,
        jobId,
        page,
        pageSize
      );
      res.status(200).json(successResponse(result, "Staging rows loaded"));
    } catch (error) {
      handleError(res, error);
    }
  },

  updateIngestionStagingRow: async (
    req: AppRequest,
    res: ExpressResponse
  ): Promise<void> => {
    const tenantId = req.tenant_id;
    const userId = req.user?.user_id;
    const jobId = req.params.jobId;
    const rowId = req.params.rowId;
    if (typeof tenantId !== "string" || !tenantId.trim() || !userId) {
      sendError(res, ERROR_CODES.FORBIDDEN, "Authenticated tenant context is required.");
      return;
    }
    if (
      typeof jobId !== "string" ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(jobId)
    ) {
      sendError(res, ERROR_CODES.INVALID_PARAMETER, "jobId must be a UUID.");
      return;
    }
    if (typeof rowId !== "string" || !/^\d{1,19}$/.test(rowId)) {
      sendError(res, ERROR_CODES.INVALID_PARAMETER, "rowId must be a positive staging-row identifier.");
      return;
    }
    try {
      const result = await dataConnectionService.updateIngestionStagingRow({
        tenantId,
        userId,
        jobId,
        rowId,
        payload: req.body?.payload
      });
      res.status(200).json(successResponse(result, "Staging row corrected and queued"));
    } catch (error) {
      handleError(res, error);
    }
  },

  retryIngestionJob: async (
    req: AppRequest,
    res: ExpressResponse
  ): Promise<void> => {
    const tenantId = req.tenant_id;
    const userId = req.user?.user_id;
    const jobId = req.params.jobId;
    if (typeof tenantId !== "string" || !tenantId.trim() || !userId) {
      sendError(res, ERROR_CODES.FORBIDDEN, "Authenticated tenant context is required.");
      return;
    }
    if (
      typeof jobId !== "string" ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(jobId)
    ) {
      sendError(res, ERROR_CODES.INVALID_PARAMETER, "jobId must be a UUID.");
      return;
    }
    try {
      const job = await dataConnectionService.retryIngestionJob(
        tenantId,
        userId,
        jobId
      );
      res.status(202).json(successResponse(job, "Ingestion retry queued"));
    } catch (error) {
      handleError(res, error);
    }
  },

  createSource: async (
    req: AppRequest,
    res: ExpressResponse
  ): Promise<void> => {
    try {
      const tenantId = req.tenant_id;

      if (typeof tenantId !== "string" || tenantId.trim().length === 0) {
        sendError(res, ERROR_CODES.FORBIDDEN, "Tenant context is required.");
        return;
      }
      const userId = req.user?.user_id;
      if (typeof userId !== "string" || !userId.trim()) {
        sendError(res, ERROR_CODES.FORBIDDEN, "Authenticated user context is required.");
        return;
      }

      const source = await dataConnectionService.createDataSource({
        tenantId,
        userId,
        payload: req.body
      });

      res
        .status(201)
        .json(successResponse(source, "Data source created successfully"));
    } catch (error) {
      handleError(res, error);
    }
  },

  setSourceActive: async (
    req: AppRequest,
    res: ExpressResponse
  ): Promise<void> => {
    try {
      const tenantId = req.tenant_id;
      const userId = req.user?.user_id;
      const sourceId = req.params.sourceId;
      const isActive = req.body?.isActive;

      if (typeof tenantId !== "string" || !tenantId.trim()) {
        sendError(res, ERROR_CODES.FORBIDDEN, "Tenant context is required.");
        return;
      }
      if (typeof userId !== "string" || !userId.trim()) {
        sendError(res, ERROR_CODES.FORBIDDEN, "Authenticated user context is required.");
        return;
      }
      if (
        typeof sourceId !== "string" ||
        !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(sourceId)
      ) {
        sendError(res, ERROR_CODES.INVALID_PARAMETER, "sourceId must be a UUID.");
        return;
      }
      if (typeof isActive !== "boolean") {
        sendError(res, ERROR_CODES.INVALID_PARAMETER, "isActive must be a boolean.");
        return;
      }

      const source = await dataConnectionService.setPersistentSourceActive({
        tenantId,
        userId,
        sourceId,
        isActive
      });
      res.status(200).json(successResponse(source, "Data source status updated"));
    } catch (error) {
      handleError(res, error);
    }
  },

  disconnectSource: async (
    req: AppRequest,
    res: ExpressResponse
  ): Promise<void> => {
    try {
      const tenantId = req.tenant_id;
      const userId = req.user?.user_id;
      const sourceId = req.params.sourceId;

      if (typeof tenantId !== "string" || !tenantId.trim()) {
        sendError(res, ERROR_CODES.FORBIDDEN, "Tenant context is required.");
        return;
      }
      if (typeof userId !== "string" || !userId.trim()) {
        sendError(res, ERROR_CODES.FORBIDDEN, "Authenticated user context is required.");
        return;
      }
      if (
        typeof sourceId !== "string" ||
        !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(sourceId)
      ) {
        sendError(res, ERROR_CODES.INVALID_PARAMETER, "sourceId must be a UUID.");
        return;
      }

      const source = await dataConnectionService.disconnectPersistentSource({
        tenantId,
        userId,
        sourceId
      });
      res.status(200).json(successResponse(source, "Data source disconnected"));
    } catch (error) {
      handleError(res, error);
    }
  }
};
