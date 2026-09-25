import { prisma } from "../src/config/database";

async function main() {
  console.log(
    "🌱 Starting Dashboard & Forecasting targeted database seeding..."
  );
  const now = new Date();
  const pastDate = (daysAgo: number) =>
    new Date(now.getTime() - daysAgo * 24 * 60 * 60 * 1000);

  const tenant_id = "c3865d65-e03a-4f34-b917-9bb93e9cfc5b";

  //   // 1. Core Tenant Company Setup
  //   const company = await prisma.company.upsert({
  //     where: { id: tenant_id },
  //     update: {},
  //     create: {
  //       id: tenant_id,
  //       businessName: "Acme Workspace Analytics",
  //       businessType: "SaaS / Software",
  //       countryCode: "JO",
  //       primaryCurrency: "JOD",
  //       timezone: "Asia/Amman",
  //       preferredLanguage: "en"
  //     }
  //   });
  //   console.log(`✅ Company configured: ${company.businessName}`);

  //   // 2. Products Setup (To power Dashboard products count & Forecasting deep dives)
  //   const productDataList = [
  //     {
  //       name: { en: "Team Workspace", ar: "مساحة عمل الفريق" },
  //       category: { en: "Business Software", ar: "برمجيات الأعمال" },
  //       price: 45.0
  //     },
  //     {
  //       name: { en: "Insights Package", ar: "حزمة الرؤى" },
  //       category: { en: "Analytics", ar: "التحليلات" },
  //       price: 89.0
  //     },
  //     {
  //       name: { en: "Support Add-on", ar: "إضافة الدعم" },
  //       category: { en: "Customer Service", ar: "خدمة العملاء" },
  //       price: 29.0
  //     },
  //     {
  //       name: { en: "Essential Office Bundle", ar: "حزمة المكتب الأساسية" },
  //       category: { en: "Business Software", ar: "برمجيات الأعمال" },
  //       price: 65.0
  //     },
  //     {
  //       name: { en: "Executive Suite", ar: "الجناح التنفيذي" },
  //       category: { en: "Enterprise", ar: "المؤسسات" },
  //       price: 129.0
  //     }
  //   ];

  //   const createdProducts = [];

  //   for (let i = 0; i < productDataList.length; i++) {
  //     const item = productDataList[i];
  //     const product = await prisma.products.create({
  //       data: {
  //         tenant_id,
  //         product_name: item.name,
  //         category: item.category,
  //         current_price: item.price,
  //         currency: "JOD",
  //         source: "MANUAL"
  //       }
  //     });
  //     createdProducts.push(product);

  //     // 3. Inventory States (Ensuring mix of in-stock, low-stock, and out-of-stock items)
  //     // Product 0: High stock, Product 1: Low stock, Product 2: Out of stock, etc.
  //     const stockQty = i === 2 ? 0 : i === 1 ? 8 : 150 + i * 45;
  //     const reorderLevel = 15;

  //     await prisma.inventory.create({
  //       data: {
  //         tenant_id,
  //         product_id: product.product_id,
  //         stock_quantity: stockQty,
  //         reorder_level: reorderLevel,
  //         safety_stock: 5,
  //         warehouse_location: `Main Warehouse - Bay ${i + 1}`
  //       }
  //     });
  //   }
  //   console.log(
  //     `✅ Seeded ${createdProducts.length} products with diversified inventory statuses`
  //   );

  //   // 4. Invoices & Sales History (Spanning current and previous intervals for growth and chart timelines)

  //   // Generate 60 historical invoices across the last 90 days to populate the sales overview chart points
  //   for (let i = 1; i <= 60; i++) {
  //     const daysAgo = Math.floor(Math.random() * 85); // Spread across past 85 days
  //     const totalAmount = 120.0 + i * 18.5;

  //     await prisma.invoices.create({
  //       data: {
  //         tenant_id,
  //         invoice_number: `INV-DS-${2026000 + i}`,
  //         customer_name: `Enterprise Client ${i}`,
  //         subtotal: totalAmount * 0.85,
  //         tax_amount: totalAmount * 0.15,
  //         total_amount: totalAmount,
  //         currency: "JOD",
  //         payment_status: "PAID", // Matching DB uppercase check constraints
  //         created_at: pastDate(daysAgo)
  //       }
  //     });
  //   }
  //   console.log(
  //     "✅ Seeded 60 paid invoices for revenue calculations and sales charts"
  //   );

  //   // 5. Demand Forecasts & Recommendations (For Forecasting overview and deep dive pages)
  //   for (const product of createdProducts) {
  //     // Create a 30-day rolling forecast entry
  //     const forecastStart = new Date();
  //     const forecastEnd = pastDate(-30); // 30 days ahead

  //     const forecast = await prisma.demand_forecasts.create({
  //       data: {
  //         tenant_id,
  //         product_id: product.product_id,
  //         forecast_start_date: forecastStart,
  //         forecast_end_date: forecastEnd,
  //         predicted_quantity: 190.0 + Math.floor(Math.random() * 100),
  //         confidence_lower_bound: 150.0,
  //         confidence_upper_bound: 280.0,
  //         model_version: "arima-ensemble-v3"
  //       }
  //     });

  //     // Link a recommendation outcome
  //     const actions = ["restock", "reduce", "monitor"];
  //     const selectedAction = actions[Math.floor(Math.random() * actions.length)];

  //     await prisma.recommendation_outcomes.create({
  //       data: {
  //         tenant_id,
  //         forecast_id: forecast.forecast_id,
  //         recommended_action: selectedAction,
  //         user_decision: "PENDING",
  //         expected_impact_json: { targetConfidence: "89%" }
  //       }
  //     });
  //   }
  //   console.log(
  //     "✅ Seeded demand forecasts and actionable recommendations for all products"
  //   );

  // 6. Audit Logs & System Alerts (To power the Recent Activity feed)

  // 6. Audit Logs & System Alerts (To power the Recent Activity feed)

  // await prisma.audit_logs.createMany({
  //   data: [
  //     {
  //       tenant_id,
  //       action_type: "FORECAST_REFRESH",
  //       target_table: "demand_forecasts",
  //       changed_data_json: {
  //         details:
  //           "Ensemble ARIMA model computed 30-day projection curves successfully.",
  //         status: "completed",
  //         severity: "SUCCESS"
  //       },
  //       created_at: pastDate(2)
  //     },
  //     {
  //       tenant_id,
  //       action_type: "INVENTORY_SYNC",
  //       target_table: "inventory",
  //       changed_data_json: {
  //         details: "Stock counts updated across Main Warehouse zones.",
  //         status: "completed",
  //         severity: "INFO"
  //       },
  //       created_at: pastDate(8)
  //     },
  //     {
  //       tenant_id,
  //       action_type: "COMPETITOR_SCRAPE",
  //       target_table: "tenant_competitors",
  //       changed_data_json: {
  //         details:
  //           "Market intelligence collected 14 new competitor price points.",
  //         status: "completed",
  //         severity: "INFO"
  //       },
  //       created_at: pastDate(24)
  //     },
  //     {
  //       tenant_id,
  //       action_type: "BULK_IMPORT",
  //       target_table: "invoices",
  //       changed_data_json: {
  //         details:
  //           "Processed 60 historical revenue records for period comparisons.",
  //         status: "completed",
  //         severity: "SUCCESS"
  //       },
  //       created_at: pastDate(48)
  //     }
  //   ],
  //   skipDuplicates: true
  // });
  // console.log("✅ Audit logs seeded for Recent Activity feed");
  // console.log("✅ Audit logs seeded for Recent Activity feed");
  // Seed Data Sources & Ingestion Jobs
  const source1 = await prisma.data_sources.create({
    data: {
      tenant_id,
      source_name: "Business Data Files",
      source_type: "documents",
      is_active: true,
      ingestion_jobs: {
        create: [
          {
            // tenant_id is omitted here; Prisma passes it down automatically!
            job_status: "COMPLETED",
            rows_processed: 18420,
            started_at: new Date(Date.now() - 3600000),
            ended_at: new Date(Date.now() - 1800000)
          }
        ]
      }
    }
  });

  const source2 = await prisma.data_sources.create({
    data: {
      tenant_id,
      source_name: "Company Website",
      source_type: "website",
      is_active: true,
      ingestion_jobs: {
        create: [
          {
            job_status: "PROCESSING",
            rows_processed: 0,
            started_at: new Date()
          }
        ]
      }
    }
  });

  const source3 = await prisma.data_sources.create({
    data: {
      tenant_id,
      source_name: "Google Analytics",
      source_type: "analytics",
      is_active: true,
      ingestion_jobs: {
        create: [
          {
            job_status: "FAILED",
            rows_processed: 7310,
            error_log: "OAuth token expired",
            started_at: new Date(Date.now() - 86400000),
            ended_at: new Date(Date.now() - 86000000)
          }
        ]
      }
    }
  });
  console.log("✅ Data sources and ingestion jobs seeded");
  console.log(
    "🚀 Dashboard and Forecasting target database successfully populated!"
  );
}

main()
  .catch((e) => {
    console.error("❌ Error seeding dashboard and forecasting data:", e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
