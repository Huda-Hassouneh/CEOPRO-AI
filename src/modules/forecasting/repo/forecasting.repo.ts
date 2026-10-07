import { prisma } from "../../../config/database.js";
import { Prisma } from "../../../generated/prisma/client.js";

/** Read one consistent tenant snapshot. Membership is validated by middleware. */
export async function loadForecastData(
  tenantId: string,
  userId: string,
  start: Date,
  end: Date,
  productId = "all",
  detail = false
) {
  return prisma.$transaction(
    async (tx) => {
      await tx.$queryRaw`
        SELECT
          set_config('app.current_tenant_id', ${tenantId}, true),
          set_config('app.current_user_id', ${userId}, true)
      `;

      const products = await tx.products.findMany({
        where: {
          tenant_id: tenantId,
          deleted_at: null
        },
        select: {
          product_id: true,
          product_name: true,
          category: true
        },
        orderBy: {
          product_id: "asc"
        }
      });

      if (
        productId !== "all" &&
        !products.some((product) => product.product_id === productId)
      ) {
        return {
          products,
          inventory: [],
          forecasts: [],
          history: [],
          modelVersions: []
        };
      }

      const scope =
        productId === "all"
          ? {}
          : {
              product_id: productId
            };

      const [inventory, forecasts, history] = await Promise.all([
        tx.inventory.findMany({
          where: {
            tenant_id: tenantId,
            ...scope,
            products: {
              tenant_id: tenantId,
              deleted_at: null
            }
          }
        }),

        tx.demand_forecasts.findMany({
          where: {
            tenant_id: tenantId,
            ...scope,
            products: {
              tenant_id: tenantId,
              deleted_at: null
            },
            OR: [
              {
                forecast_start_date: {
                  lte: end
                },
                forecast_end_date: {
                  gte: start
                }
              },
              {
                forecast_start_date: null,
                forecast_end_date: null,
                forecast_target_date: {
                  gte: start,
                  lte: end
                }
              }
            ]
          },
          include: {
            recommendation_outcomes: {
              where: {
                tenant_id: tenantId
              },
              orderBy: [
                {
                  created_at: {
                    sort: "desc",
                    nulls: "last"
                  }
                },
                {
                  recommendation_id: "desc"
                }
              ],
              take: 1
            }
          },
          orderBy: [
            {
              created_at: {
                sort: "desc",
                nulls: "last"
              }
            },
            {
              forecast_id: "desc"
            }
          ]
        }),

        detail
          ? tx.$queryRaw<Array<{ date: string; units: bigint }>>`
              SELECT
                to_char(
                  transaction_date AT TIME ZONE 'UTC',
                  'YYYY-MM-DD'
                ) AS date,
                SUM(quantity_sold)::bigint AS units
              FROM transactions
              WHERE tenant_id = ${tenantId}::uuid
                AND product_id = ${productId}::uuid
                AND transaction_date >= ${start}
                AND transaction_date < ${end}
              GROUP BY 1
              ORDER BY 1
            `
          : Promise.resolve([])
      ]);

      /*
       * demand_forecasts stores the model version string used to generate
       * each forecast. Load only model registry rows required by this
       * snapshot.
       *
       * Do not use findFirst() here because model_versions.version is not
       * currently enforced as globally unique by the database schema.
       */
      const modelVersionNames = [
        ...new Set(
          forecasts
            .map((forecast) => forecast.model_version?.trim())
            .filter(
              (version): version is string =>
                typeof version === "string" && version.length > 0
            )
        )
      ];

      const modelVersions =
        modelVersionNames.length > 0
          ? await tx.model_versions.findMany({
              where: {
                version: {
                  in: modelVersionNames
                }
              },
              select: {
                model_version_id: true,
                model_name: true,
                version: true,
                status: true,
                trained_at: true,
                metrics: true,
                created_at: true
              },
              orderBy: [
                {
                  created_at: {
                    sort: "desc",
                    nulls: "last"
                  }
                },
                {
                  model_version_id: "desc"
                }
              ]
            })
          : [];

      return {
        products,
        inventory,
        forecasts,
        history,
        modelVersions
      };
    },
    {
      isolationLevel: Prisma.TransactionIsolationLevel.RepeatableRead
    }
  );
}

function localizedText(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  const record = value as Record<string, unknown>;
  for (const key of ["en", "ar"]) {
    const candidate = record[key];
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
  }
  return null;
}

export async function loadForecastGenerationInput(input: {
  tenantId: string;
  userId: string;
  productId: string;
}) {
  return prisma.$transaction(async (tx) => {
    await tx.$queryRaw`
      SELECT
        set_config('app.current_tenant_id', ${input.tenantId}, true),
        set_config('app.current_user_id', ${input.userId}, true)
    `;

    const product = await tx.products.findFirst({
      where: {
        tenant_id: input.tenantId,
        product_id: input.productId,
        deleted_at: null
      },
      select: {
        product_id: true,
        product_name: true,
        category: true,
        current_price: true
      }
    });
    if (!product) return null;

    const now = new Date();
    const utcToday = new Date(
      Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
    );
    const start = new Date(utcToday.getTime() - 365 * 24 * 60 * 60 * 1000);
    const end = new Date(utcToday.getTime() + 24 * 60 * 60 * 1000);

    const [inventory, transactions] = await Promise.all([
      tx.inventory.findMany({
        where: { tenant_id: input.tenantId, product_id: input.productId },
        select: { stock_quantity: true }
      }),
      tx.$queryRaw<
        Array<{
          transaction_date: string;
          quantity: bigint;
          unit_price: number;
        }>
      >`
        SELECT
          to_char(transaction_date AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS transaction_date,
          SUM(quantity_sold)::bigint AS quantity,
          CASE
            WHEN SUM(quantity_sold) = 0 THEN AVG(unit_price)
            ELSE SUM(quantity_sold * unit_price) / SUM(quantity_sold)
          END::double precision AS unit_price
        FROM transactions
        WHERE tenant_id = ${input.tenantId}::uuid
          AND product_id = ${input.productId}::uuid
          AND transaction_date >= ${start}
          AND transaction_date < ${end}
        GROUP BY 1
        ORDER BY 1
      `
    ]);

    return {
      productId: product.product_id,
      productName: localizedText(product.product_name),
      category: localizedText(product.category),
      currentPrice: Number(product.current_price),
      currentStock:
        inventory.length > 0
          ? inventory.reduce((sum, row) => sum + row.stock_quantity, 0)
          : null,
      transactions: transactions.map((row) => ({
        transaction_date: row.transaction_date,
        quantity: Number(row.quantity),
        unit_price: Number(row.unit_price)
      }))
    };
  });
}

export async function persistGeneratedForecast(input: {
  tenantId: string;
  userId: string;
  productId: string;
  forecastStartDate: Date;
  forecastEndDate: Date;
  forecastTargetDate: Date;
  expectedDemand: number;
  source: "xgboost" | "baseline";
  confidenceScore: number;
  transactionsUsed: number;
  horizonDays: number;
  dataSufficiency: Prisma.InputJsonValue;
}): Promise<{ forecastId: string; evidenceId: string }> {
  return prisma.$transaction(async (tx) => {
    await tx.$queryRaw`
      SELECT
        set_config('app.current_tenant_id', ${input.tenantId}, true),
        set_config('app.current_user_id', ${input.userId}, true)
    `;

    const forecast = await tx.demand_forecasts.create({
      data: {
        tenant_id: input.tenantId,
        product_id: input.productId,
        forecast_start_date: input.forecastStartDate,
        forecast_end_date: input.forecastEndDate,
        forecast_target_date: input.forecastTargetDate,
        expected_demand: Math.round(input.expectedDemand),
        confidence_range_lower: null,
        confidence_range_upper: null,
        model_version: input.source,
        features_used: {
          source: input.source,
          transactions_used: input.transactionsUsed,
          horizon_days: input.horizonDays,
          data_sufficiency: input.dataSufficiency,
          confidence_score: input.confidenceScore
        }
      },
      select: { forecast_id: true }
    });

    const evidence = await tx.evidence_records.create({
      data: {
        tenant_id: input.tenantId,
        forecast_id: forecast.forecast_id,
        source_module: "forecasting",
        metric_name: "expected_demand",
        metric_value_json: {
          expected_demand: input.expectedDemand,
          forecast_target_date: input.forecastTargetDate.toISOString().slice(0, 10),
          source: input.source,
          horizon_days: input.horizonDays
        },
        source_record_ids: {
          product_id: input.productId,
          transactions_used: input.transactionsUsed
        },
        confidence_score: input.confidenceScore,
        explanation_text: null,
        model_version: input.source
      },
      select: { evidence_id: true }
    });

    return { forecastId: forecast.forecast_id, evidenceId: evidence.evidence_id };
  });
}
