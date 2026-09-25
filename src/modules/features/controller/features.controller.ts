import { NextFunction, Request, Response } from "express";
import {
  incrementUsage,
  getRemainingUsage,
  documentsRepo
} from "../repo/usage.repo.js";
import { successResponse, errorResponse } from "../../../types/response.js"; // adjust path
import { ERROR_CODES } from "../../../errors/error-codes.js"; // adjust path
import { ERROR_DEFINITIONS } from "../../../errors/error-definitions.js"; // adjust path
import { ragService } from "../service/features.service.js";

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
      console.log(formData);

      // const aiResponse = await fetch(`${AI_SERVICE_URL}/extraction/upload`, {
      //   method: "POST",
      //   body: formData
      // });

      // if (!aiResponse.ok) {
      //   const errDef = ERROR_DEFINITIONS[ERROR_CODES.EXTERNAL_SERVICE_ERROR];
      //   res
      //     .status(errDef.statusCode)
      //     .json(
      //       errorResponse(
      //         errDef.message,
      //         errDef.statusCode,
      //         ERROR_CODES.EXTERNAL_SERVICE_ERROR,
      //         "AI Extraction Service failed"
      //       )
      //     );
      //   return;
      // }

      // const data = await aiResponse.json();
      const data = {
        job_id: "a5d8b76e-34e8-48b2-b5e1-88981f2c24ef",
        template_mode: "best-effort mapping",
        is_template_compliant: false,
        rows_processed: 150,
        rows_partial: 12,
        rows_failed: 3,
        data_loss_pct: 2.0,
        header_coverage_ratio: 0.88,
        minio_object_key: "raw-uploads/tenant-550e8400/sales_data_q3.xlsx",
        row_outcomes: [
          {
            row_index: 14,
            mode: "best-effort",
            field_errors: ["missing_discount_rate"],
            error: null
          },
          {
            row_index: 42,
            mode: "rejected",
            field_errors: ["invalid_price_format", "missing_product_sku"],
            error: "Failed to parse unit price as valid decimal"
          },
          {
            row_index: 89,
            mode: "rejected",
            field_errors: ["negative_quantity"],
            error: "Quantity must be greater than zero"
          }
        ],
        promotion: {
          rows_promoted: 135,
          rows_skipped_incomplete: 12,
          rows_failed: 3,
          products_created: 18,
          errors: [
            "Row 42: Product SKU cannot be blank",
            "Row 89: Line item quantity cannot be negative"
          ]
        },
        currency_resolution: {
          currency: "USD",
          needs_confirmation: true
        }
      };

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
            ERROR_CODES.INTERNAL_SERVER_ERROR
          )
        );
    }
  },

  processPending: async (req: any, res: Response): Promise<void> => {
    const usage = await getRemainingUsage(req.tenant_id, "document_extraction");
    const requestedLimit = Number(req.query.limit ?? 100);

    const allowedLimit =
      usage?.remaining === null
        ? requestedLimit
        : Math.min(requestedLimit, usage?.remaining ?? 0);
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
      console.log({ query_text });

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

      // const aiResponse = await fetch(
      //   `${AI_SERVICE_URL}/rag/query?query_text=${encodeURIComponent(query_text as string)}&top_k=${top_k}`,
      //   { method: "POST" }
      // );

      // if (!aiResponse.ok) {
      //   const errDef = ERROR_DEFINITIONS[ERROR_CODES.EXTERNAL_SERVICE_ERROR];
      //   res
      //     .status(errDef.statusCode)
      //     .json(
      //       errorResponse(
      //         errDef.message,
      //         errDef.statusCode,
      //         ERROR_CODES.EXTERNAL_SERVICE_ERROR,
      //         "AI RAG Service failed"
      //       )
      //     );
      //   return;
      // }

      // const data = await aiResponse.json();
      const data = {
        answer:
          "MinIO utilizes erasure coding rather than traditional data replication to ensure high resilience and protect against multiple drive failures.",
        sources: [
          {
            source_index: 1,
            chunk_id: "c1f7a3b2-9d4e-48c5-a2b1-3e6f9a8d7c4b",
            score: 0.94
          },
          {
            source_index: 2,
            chunk_id: "e8d9c0b1-4a5f-42e3-b6c7-1d2a3f4e5b6c",
            score: 0.88
          }
        ]
      };
      await incrementUsage(tenantId, "rag_assistant", 1);

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
            ERROR_CODES.INTERNAL_SERVER_ERROR
          )
        );
    }
  },
  // getChunk: async (req: any, res: Response): Promise<void> => {
  //   try {
  //     const tenantId = req.tenant_id;
  //     const { chunk_id } = req.params;

  //     const chunkData = await ragService.fetchChunkDetails(tenantId, chunk_id);

  //     res
  //       .status(200)
  //       .json(successResponse(chunkData, "Chunk fetched successfully"));
  //   } catch (error: any) {
  //     console.error("Chunk Fetch Error:", error);

  //     if (error.code === "NOT_FOUND") {
  //       const errDef = ERROR_DEFINITIONS[ERROR_CODES.RESOURCE_NOT_FOUND];
  //       res
  //         .status(errDef.statusCode)
  //         .json(
  //           errorResponse(
  //             errDef.message,
  //             errDef.statusCode,
  //             ERROR_CODES.RESOURCE_NOT_FOUND,
  //             error.message
  //           )
  //         );
  //       return;
  //     }

  //     const errDef = ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];
  //     res
  //       .status(errDef.statusCode)
  //       .json(
  //         errorResponse(
  //           errDef.message,
  //           errDef.statusCode,
  //           ERROR_CODES.INTERNAL_SERVER_ERROR
  //         )
  //       );
  //   }
  // },
  getChunk: async (
    req: any,
    res: Response,
    next: NextFunction
  ): Promise<void> => {
    try {
      const tenantId = req.tenant_id;
      const { chunk_id } = req.params;

      // -----------------------------------------------------
      // 1. MOCKED DATA FOR LOCAL TESTING
      // Comment out the real service call:
      // const chunkData = await ragService.fetchChunkDetails(tenantId, chunk_id);
      // -----------------------------------------------------

      // Map of mock chunk IDs (matching the queryAssistant mock) to their extracted text and source file
      const mockChunks: Record<string, any> = {
        "c1f7a3b2-9d4e-48c5-a2b1-3e6f9a8d7c4b": {
          chunk_id: "c1f7a3b2-9d4e-48c5-a2b1-3e6f9a8d7c4b",
          text_content:
            "The expected Q3 marketing budget is strictly capped at $150,000. This includes $50,000 allocated for digital ad spend across social channels, $75,000 for regional event sponsorships, and $25,000 reserved for influencer partnerships and affiliate programs.",
          file_name: "2026_Q3_Marketing_Strategy.pdf"
        },
        "e8d9c0b1-4a5f-42e3-b6c7-1d2a3f4e5b6c": {
          chunk_id: "e8d9c0b1-4a5f-42e3-b6c7-1d2a3f4e5b6c",
          text_content:
            "MinIO utilizes erasure coding rather than traditional data replication to ensure high resilience and protect against multiple drive failures. This allows the storage cluster to lose up to half of its drives and still reconstruct the missing data automatically during data ingestion pipelines.",
          file_name: "System_Architecture_Guide.pdf"
        }
      };

      const chunkData = mockChunks[chunk_id];

      // -----------------------------------------------------
      // 2. Handle Not Found Error (If user clicks a random ID)
      // -----------------------------------------------------
      if (!chunkData) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.RESOURCE_NOT_FOUND];
        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.RESOURCE_NOT_FOUND,
              `Chunk ${chunk_id} not found in mock data.`
            )
          );
        return;
      }

      // -----------------------------------------------------
      // 3. Return Successful Payload
      // -----------------------------------------------------
      res
        .status(200)
        .json(successResponse(chunkData, "Chunk fetched successfully"));
    } catch (error: any) {
      console.error("Chunk Fetch Error:", error);
      const errDef = ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];
      res
        .status(errDef.statusCode)
        .json(
          errorResponse(
            errDef.message,
            errDef.statusCode,
            ERROR_CODES.INTERNAL_SERVER_ERROR
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
            ERROR_CODES.INTERNAL_SERVER_ERROR
          )
        );
    }
  }
};

export const sentimentController = {
  analyzePending: async (req: any, res: Response): Promise<void> => {
    try {
      const tenantId = req.tenant_id;

      const requestedBatchSize = Number(req.query.batch_size ?? 100);

      // -----------------------------------------------------
      // 1. Get remaining plan quota
      // -----------------------------------------------------

      const usage = await getRemainingUsage(tenantId, "sentiment_analysis");

      if (!usage) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.FORBIDDEN];

        res
          .status(errDef.statusCode)
          .json(
            errorResponse(
              errDef.message,
              errDef.statusCode,
              ERROR_CODES.FORBIDDEN,
              "Sentiment analysis is not available for this subscription."
            )
          );

        return;
      }

      // -----------------------------------------------------
      // 2. Block if quota is exhausted
      // -----------------------------------------------------

      if (usage.isExceeded) {
        const errDef = ERROR_DEFINITIONS[ERROR_CODES.PAYMENT_REQUIRED];

        res.status(errDef.statusCode).json(
          errorResponse(
            errDef.message,
            errDef.statusCode,
            ERROR_CODES.PAYMENT_REQUIRED,
            {
              message: "Sentiment analysis quota has been reached.",

              current_usage: usage.currentUsage,

              limit: usage.limit,

              remaining: 0
            }
          )
        );

        return;
      }

      // -----------------------------------------------------
      // 3. Limit batch to remaining quota
      // -----------------------------------------------------

      const allowedBatchSize =
        usage.remaining === null
          ? requestedBatchSize
          : Math.min(requestedBatchSize, usage.remaining);

      // -----------------------------------------------------
      // 4. Call AI using allowed amount
      // -----------------------------------------------------

      const url = new URL(`${AI_SERVICE_URL}/sentiment/analyze-pending`);

      url.searchParams.append("batch_size", String(allowedBatchSize));

      const aiResponse = await fetch(url.toString(), {
        method: "POST",

        headers: {
          Authorization: req.headers.authorization
        }
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
              "AI Sentiment Service failed"
            )
          );

        return;
      }

      const data = await aiResponse.json();

      // -----------------------------------------------------
      // 5. Record what AI ACTUALLY processed
      // -----------------------------------------------------

      const analyzedCount = Number(data.analyzed_count ?? 0);

      if (analyzedCount > 0) {
        await incrementUsage(tenantId, "sentiment_analysis", analyzedCount);
      }

      res.status(200).json(
        successResponse(
          {
            status: data.status,

            analyzed_count: analyzedCount,

            requested_batch_size: requestedBatchSize,

            allowed_batch_size: allowedBatchSize
          },

          "Batch sentiment analysis completed"
        )
      );
    } catch (error) {
      console.error("Sentiment Controller Error:", error);

      const errDef = ERROR_DEFINITIONS[ERROR_CODES.INTERNAL_SERVER_ERROR];

      res
        .status(errDef.statusCode)
        .json(
          errorResponse(
            errDef.message,
            errDef.statusCode,
            ERROR_CODES.INTERNAL_SERVER_ERROR
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
            ERROR_CODES.INTERNAL_SERVER_ERROR
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
            ERROR_CODES.INTERNAL_SERVER_ERROR
          )
        );
    }
  }
};

export const documentController = {
  listDocuments: async (req: any, res: Response): Promise<void> => {
    try {
      const tenantId = req.tenant_id; // Attached by your authenticateUser middleware
      const page = parseInt(req.query.page as string) || 1;
      const pageSize = 10;

      // Query the Prisma table defined in your schema
      // const documents = await getDocuments({
      //   page,
      //   pageSize,
      //   tenant_id: tenantId
      // });

      // const total = await documentsRepo.getCountDocuments(tenantId);

      // --- MOCKED DATA FOR LOCAL TESTING ---
      // Commenting out the actual repository calls:
      // const documents = await documentsRepo.getDocuments({ page, pageSize, tenant_id: tenantId });
      // const total = await getCountDocuments(tenantId);

      const total = 12; // Mock total number of documents

      const documents = [
        {
          document_id: "f47ac10b-58cc-4372-a567-0e02b2c3d479",
          tenant_id: tenantId,
          file_name: "2026_Q3_Marketing_Strategy.pdf",
          storage_bucket_path: `raw-uploads/${tenantId}/2026_Q3_Marketing_Strategy.pdf`,
          file_size_bytes: 4520192n, // 4.5 MB (Note: Prisma returns BigInt for this field)
          content_type: "application/pdf",
          uploaded_by_user_id: "e58b123d-4567-890a-bcde-f1234567890a",
          uploaded_at: new Date("2026-09-24T10:00:00Z")
        },
        {
          document_id: "c1f7a3b2-9d4e-48c5-a2b1-3e6f9a8d7c4b",
          tenant_id: tenantId,
          file_name: "Competitor_Analysis_Q2.xlsx",
          storage_bucket_path: `raw-uploads/${tenantId}/Competitor_Analysis_Q2.xlsx`,
          file_size_bytes: 1245184n, // 1.2 MB
          content_type:
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          uploaded_by_user_id: "e58b123d-4567-890a-bcde-f1234567890a",
          uploaded_at: new Date("2026-09-22T14:30:00Z")
        },
        {
          document_id: "a0b1c2d3-e4f5-6789-abcd-ef0123456789",
          tenant_id: tenantId,
          file_name: "Employee_Handbook_v3.docx",
          storage_bucket_path: `raw-uploads/${tenantId}/Employee_Handbook_v3.docx`,
          file_size_bytes: 845200n, // 845 KB
          content_type:
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          uploaded_by_user_id: "e58b123d-4567-890a-bcde-f1234567890a",
          uploaded_at: new Date("2026-09-15T09:15:00Z")
        }
      ];
      const formattedDocuments = documents.map((doc) => ({
        ...doc,
        file_size_bytes: doc.file_size_bytes.toString()
      }));
      // -------------------------------------
      res.status(200).json(
        successResponse(
          {
            documents: formattedDocuments,
            pagination: {
              page,
              pageSize,
              total,
              totalPages: Math.ceil(total / pageSize)
            }
          },
          "Documents fetched successfully"
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
            ERROR_CODES.INTERNAL_SERVER_ERROR
          )
        );
    }
  }
};
