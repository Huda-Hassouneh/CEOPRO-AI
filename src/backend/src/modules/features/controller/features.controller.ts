import { Request, Response } from "express";
import { incrementUsage } from "../repo/usage.repo.js";
import { successResponse, errorResponse } from "../../../types/response.js"; // adjust path
import { ERROR_CODES } from "../../../errors/error-codes.js"; // adjust path
import { ERROR_DEFINITIONS } from "../../../errors/error-defentions.js"; // adjust path

const AI_SERVICE_URL = process.env.AI_SERVICE_URL || "http://localhost:8000";

export const extractionController = {
  uploadFile: async (req: any, res: Response): Promise<void> => {
    try {
      const tenantId = req.tenant_id;
      const file = req.file;

      if (!file) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.INVALID_REQUEST];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.INVALID_REQUEST,
              "File upload is required."
            )
          );
        return;
      }

      const formData = new FormData();
      formData.append(
        "file",
        new Blob([file.buffer], { type: file.mimetype }),
        file.originalname
      );

      const aiResponse = await fetch(`${AI_SERVICE_URL}/extraction/upload`, {
        method: "POST",
        body: formData
      });

      if (!aiResponse.ok) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.EXTERNAL_SERVICE_ERROR];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.EXTERNAL_SERVICE_ERROR,
              "AI Extraction Service failed"
            )
          );
        return;
      }

      const data = await aiResponse.json();
      await incrementUsage(tenantId, "document_extraction");

      res.status(200).json(
        successResponse(
          {
            job_id: data.job_id,
            template_mode: data.template_mode,
            is_template_compliant: data.is_template_compliant,
            rows_processed: data.rows_processed,
            rows_partial: data.rows_partial,
            rows_failed: data.rows_failed,
            data_loss_pct: data.data_loss_pct,
            header_coverage_ratio: data.header_coverage_ratio,
            row_outcomes: data.row_outcomes,
            promotion: data.promotion,
            currency_resolution: data.currency_resolution
          },
          "Document extraction successful"
        )
      );
    } catch (error) {
      console.error("Extraction Controller Error:", error);
      const errDef = ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];
      res
        .status(errDef.statusCode)
        .json(
          errorResponse(
            errDef.message,
            errDef.statusCode,
            ERROR_CODES.INTERNAL_SERVER_ERROR,
            error instanceof Error ? error.message : error
          )
        );
    }
  },

  processPending: async (req: any, res: Response): Promise<void> => {
    res
      .status(200)
      .json(
        successResponse(
          { message: "Pending extraction triggered" },
          "Process pending successful"
        )
      );
  }
};

export const ragController = {
  queryAssistant: async (req: any, res: Response): Promise<void> => {
    try {
      const { query_text, top_k = 5 } = req.query;
      const tenantId = req.tenant_id;

      if (!query_text) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.INVALID_REQUEST];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.INVALID_REQUEST,
              "query_text is required."
            )
          );
        return;
      }

      const aiResponse = await fetch(
        `${AI_SERVICE_URL}/rag/query?query_text=${encodeURIComponent(query_text as string)}&top_k=${top_k}`,
        { method: "POST" }
      );

      if (!aiResponse.ok) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.EXTERNAL_SERVICE_ERROR];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.EXTERNAL_SERVICE_ERROR,
              "AI RAG Service failed"
            )
          );
        return;
      }

      const data = await aiResponse.json();
      await incrementUsage(tenantId, "rag_assistant");

      res.status(200).json(
        successResponse(
          {
            answer: data.answer,
            sources: data.sources
          },
          "Assistant query successful"
        )
      );
    } catch (error) {
      console.error("RAG Controller Error:", error);
      const errDef = ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];
      res
        .status(errDef.statusCode)
        .json(
          errorResponse(
            errDef.message,
            errDef.statusCode,
            ERROR_CODES.INTERNAL_SERVER_ERROR,
            error instanceof Error ? error.message : error
          )
        );
    }
  }
};

export const pricingController = {
  getRecommendation: async (req: any, res: Response): Promise<void> => {
    try {
      const { product_id } = req.query;
      const tenantId = req.tenant_id;

      if (!product_id) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.INVALID_REQUEST];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.INVALID_REQUEST,
              "product_id query parameter is required."
            )
          );
        return;
      }

      const aiResponse = await fetch(
        `${AI_SERVICE_URL}/pricing/recommend?product_id=${product_id}`,
        { method: "POST" }
      );

      if (!aiResponse.ok) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.EXTERNAL_SERVICE_ERROR];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.EXTERNAL_SERVICE_ERROR,
              "AI Pricing Service failed"
            )
          );
        return;
      }

      const data = await aiResponse.json();
      await incrementUsage(tenantId, "ai_pricing");

      res.status(200).json(
        successResponse(
          {
            status: data.status,
            action: data.action,
            current_price: data.current_price,
            suggested_price: data.suggested_price,
            clamped: data.clamped,
            max_change_pct: data.max_change_pct,
            min_margin_pct: data.min_margin_pct,
            floor_price: data.floor_price,
            market_min: data.market_min,
            market_max: data.market_max,
            market_avg: data.market_avg,
            market_median: data.market_median,
            matched_competitor_count: data.matched_competitor_count,
            confidence_score: data.confidence_score,
            explanation: data.explanation,
            evidence_id: data.evidence_id
          },
          "Pricing recommendation fetched successfully"
        )
      );
    } catch (error) {
      console.error("Pricing Controller Error:", error);
      const errDef = ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];
      res
        .status(errDef.statusCode)
        .json(
          errorResponse(
            errDef.message,
            errDef.statusCode,
            ERROR_CODES.INTERNAL_SERVER_ERROR,
            error instanceof Error ? error.message : error
          )
        );
    }
  }
};

export const sentimentController = {
  analyzePending: async (req: any, res: Response): Promise<void> => {
    try {
      const { batch_size } = req.query;
      const tenantId = req.tenant_id;

      const url = new URL(`${AI_SERVICE_URL}/sentiment/analyze-pending`);
      if (batch_size) url.searchParams.append("batch_size", String(batch_size));

      const aiResponse = await fetch(url.toString(), { method: "POST" });

      if (!aiResponse.ok) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.EXTERNAL_SERVICE_ERROR];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.EXTERNAL_SERVICE_ERROR,
              "AI Sentiment Service failed"
            )
          );
        return;
      }

      const data = await aiResponse.json();
      await incrementUsage(tenantId, "sentiment_analysis");

      res.status(200).json(
        successResponse(
          {
            status: data.status,
            analyzed_count: data.analyzed_count
          },
          "Batch sentiment analysis completed"
        )
      );
    } catch (error) {
      console.error("Sentiment Controller Error (analyzePending):", error);
      const errDef = ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];
      res
        .status(errDef.statusCode)
        .json(
          errorResponse(
            errDef.message,
            errDef.statusCode,
            ERROR_CODES.INTERNAL_SERVER_ERROR,
            error instanceof Error ? error.message : error
          )
        );
    }
  },

  getSummary: async (req: any, res: Response): Promise<void> => {
    try {
      const { subject_type, subject_id } = req.query;

      if (!subject_type || !subject_id) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.INVALID_REQUEST];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.INVALID_REQUEST,
              "subject_type and subject_id are required."
            )
          );
        return;
      }

      const url = new URL(`${AI_SERVICE_URL}/sentiment/summary`);
      url.searchParams.append("subject_type", String(subject_type));
      url.searchParams.append("subject_id", String(subject_id));

      const aiResponse = await fetch(url.toString(), { method: "GET" });

      if (!aiResponse.ok) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.EXTERNAL_SERVICE_ERROR];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.EXTERNAL_SERVICE_ERROR,
              "AI Sentiment Service failed"
            )
          );
        return;
      }

      const data = await aiResponse.json();

      res.status(200).json(
        successResponse(
          {
            status: data.status,
            sentiment_score: data.sentiment_score,
            label_counts: data.label_counts,
            sample_size: data.sample_size,
            evidence_id: data.evidence_id
          },
          "Sentiment summary retrieved successfully"
        )
      );
    } catch (error) {
      console.error("Sentiment Controller Error (getSummary):", error);
      const errDef = ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];
      res
        .status(errDef.statusCode)
        .json(
          errorResponse(
            errDef.message,
            errDef.statusCode,
            ERROR_CODES.INTERNAL_SERVER_ERROR,
            error instanceof Error ? error.message : error
          )
        );
    }
  }
};

export const mpiController = {
  getSummary: async (req: any, res: Response): Promise<void> => {
    try {
      const { subject_type, subject_id } = req.query;

      if (!subject_type || !subject_id) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.INVALID_REQUEST];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.INVALID_REQUEST,
              "subject_type and subject_id are required."
            )
          );
        return;
      }

      const url = new URL(`${AI_SERVICE_URL}/mpi/summary`);
      url.searchParams.append("subject_type", String(subject_type));
      url.searchParams.append("subject_id", String(subject_id));

      const aiResponse = await fetch(url.toString(), { method: "GET" });

      if (!aiResponse.ok) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.EXTERNAL_SERVICE_ERROR];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.EXTERNAL_SERVICE_ERROR,
              "AI MPI Service failed"
            )
          );
        return;
      }

      const data = await aiResponse.json();

      res.status(200).json(
        successResponse(
          {
            status: data.status,
            mpi: data.mpi,
            weighted_sentiment_score: data.weighted_sentiment_score,
            volume_confidence: data.volume_confidence,
            review_count: data.review_count,
            avg_recency_weight: data.avg_recency_weight,
            avg_reliability_weight: data.avg_reliability_weight,
            label_counts: data.label_counts,
            confidence_score: data.confidence_score,
            sample_size: data.sample_size,
            evidence_id: data.evidence_id
          },
          "Market Perception Index fetched successfully"
        )
      );
    } catch (error) {
      console.error("MPI Controller Error:", error);
      const errDef = ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];
      res
        .status(errDef.statusCode)
        .json(
          errorResponse(
            errDef.message,
            errDef.statusCode,
            ERROR_CODES.INTERNAL_SERVER_ERROR,
            error instanceof Error ? error.message : error
          )
        );
    }
  }
};
