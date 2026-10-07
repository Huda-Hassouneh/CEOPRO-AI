import type { Response } from "express";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import type { AppRequest } from "../../../types/request.js";
import { errorResponse } from "../../../types/response.js";
import { dataConnectionController } from "../../dataconnection/controller/dataconnection.controller.js";

export const extractionController = {
  // Keep the historical CEOPRO route while sharing the current extraction
  // orchestration and persistence implementation.
  uploadFile: dataConnectionController.uploadFile,

  // Gradio extraction processes a submitted file synchronously and has no
  // equivalent process-pending API. Keep the old route explicit for clients.
  processPending: async (_req: AppRequest, res: Response): Promise<void> => {
    res.status(501).json(
      errorResponse(
        "This operation is unsupported by the current AI extraction contract. Submit a file to extract it.",
        501,
        ERROR_CODES.NOT_IMPLEMENTED
      )
    );
  }
};
