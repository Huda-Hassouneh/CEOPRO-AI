import { prisma } from "../../../src/config/database.js";
import { inBatches } from "../helpers/batch.js";
import type { SeedClock } from "../helpers/time.js";

export async function seedForecasting(args: {
  products: any[];
  uuid: (key: string) => string;
  clock: SeedClock;
}) {
  const { products, uuid, clock } = args;

  const forecasts = products
    .filter((_, index) => index % 9 !== 0)
    .flatMap((product, productIndex) => {
      const rows: any[] = [];

      // Historical daily forecasts: today - 30 days through yesterday.
      for (let day = 0; day < 30; day++) {
        const forecastDate = clock.ago(30 - day);
        const baseDemand = 2 + (productIndex % 8);
        const dailyDemand =
          baseDemand + ((day + productIndex) % 4) + Math.floor(day / 10);

        rows.push({
          forecast_id: uuid(
            `forecast:${product.product_id}:previous:${day}`
          ),
          tenant_id: product.tenant_id,
          product_id: product.product_id,
          forecast_start_date: forecastDate,
          forecast_end_date: forecastDate,
          forecast_target_date: forecastDate,
          expected_demand: dailyDemand,
          confidence_range_lower: Math.max(0, dailyDemand - 2),
          confidence_range_upper: dailyDemand + 3,
          model_version: "synthetic-integration-v2-daily",
          features_used: {
            fixture: true,
            granularity: "daily",
            horizon: "previous-30-days"
          },
          created_at: clock.ago(31)
        });
      }

      // Current/future daily forecasts: today through today + 29 days.
      const currentDaily: Array<{ date: Date; expectedDemand: number }> = [];

      for (let day = 0; day < 30; day++) {
        const forecastDate = clock.ago(-day);
        const baseDemand = 3 + (productIndex % 9);
        let dailyDemand: number;

        switch (productIndex % 3) {
          case 0:
            dailyDemand = baseDemand + Math.floor(day / 5);
            break;
          case 1:
            dailyDemand = Math.max(
              1,
              baseDemand + 6 - Math.floor(day / 5)
            );
            break;
          default:
            dailyDemand = baseDemand;
            break;
        }

        currentDaily.push({
          date: forecastDate,
          expectedDemand: dailyDemand
        });

        rows.push({
          forecast_id: uuid(
            `forecast:${product.product_id}:current:${day}`
          ),
          tenant_id: product.tenant_id,
          product_id: product.product_id,
          forecast_start_date: forecastDate,
          forecast_end_date: forecastDate,
          forecast_target_date: forecastDate,
          expected_demand: dailyDemand,
          confidence_range_lower: Math.max(0, dailyDemand - 2),
          confidence_range_upper: dailyDemand + 3,
          model_version: "synthetic-integration-v2-daily",
          features_used: {
            fixture: true,
            granularity: "daily",
            horizon: "next-30-days"
          },
          created_at: clock.now
        });
      }

      const addHorizonForecast = (horizonDays: 7 | 30) => {
        const horizon = currentDaily.slice(0, horizonDays);

        if (horizon.length !== horizonDays) {
          return;
        }

        const expectedDemand = horizon.reduce(
          (sum, item) => sum + item.expectedDemand,
          0
        );

        // Synthetic DEV/TEST uncertainty only; not a calibrated production CI.
        const fixtureMargin = Math.max(
          3,
          Math.ceil(expectedDemand * 0.12)
        );

        rows.push({
          forecast_id: uuid(
            `forecast:${product.product_id}:current-horizon:${horizonDays}`
          ),
          tenant_id: product.tenant_id,
          product_id: product.product_id,
          forecast_start_date: horizon[0]!.date,
          forecast_end_date: horizon[horizon.length - 1]!.date,
          forecast_target_date: null,
          expected_demand: expectedDemand,
          confidence_range_lower: Math.max(
            0,
            expectedDemand - fixtureMargin
          ),
          confidence_range_upper: expectedDemand + fixtureMargin,
          model_version: `synthetic-integration-v3-${horizonDays}d-horizon`,
          features_used: {
            fixture: true,
            granularity: "horizon",
            horizon_days: horizonDays,
            confidence_source: "synthetic-fixture-only"
          },
          created_at: clock.now
        });
      };

      addHorizonForecast(7);
      addHorizonForecast(30);

      return rows;
    });

  await inBatches(forecasts, (batch) =>
    prisma.demand_forecasts.createMany({
      data: batch,
      skipDuplicates: true
    })
  );

  const recommendationForecasts = forecasts.filter(
    (forecast) =>
      forecast.model_version === "synthetic-integration-v3-7d-horizon" ||
      forecast.model_version === "synthetic-integration-v3-30d-horizon"
  );

  const recommendations = recommendationForecasts.map(
    (forecast, index) => {
      const action =
        index % 3 === 0
          ? "restock"
          : index % 3 === 1
            ? "reduce"
            : "monitor";

      return {
        recommendation_id: uuid(
          `recommendation:${forecast.forecast_id}`
        ),
        tenant_id: forecast.tenant_id,
        forecast_id: forecast.forecast_id,
        recommended_action: action,
        expected_impact_json: {
          fixture: true,
          source: "synthetic-demand-forecast",
          horizon:
            forecast.model_version ===
            "synthetic-integration-v3-7d-horizon"
              ? "7-days"
              : "30-days"
        },
        user_decision: "PENDING",
        actual_outcome_json: {
          fixture: true,
          status: "not_observed"
        },
        created_at: clock.now,
        updated_at: clock.now
      };
    }
  );

  await inBatches(recommendations, (batch) =>
    prisma.recommendation_outcomes.createMany({
      data: batch,
      skipDuplicates: true
    })
  );

  return { forecasts, recommendations };
}
