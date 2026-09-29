/** Isolated, repeatable fixtures for the Dashboard's Growth and Review Sentiment KPIs. */
import { createHash } from "node:crypto";
import { prisma } from "../src/config/database.js";

const marker = "DASHBOARD_METRIC_TEST_V1";
const tenantId = process.env.DASHBOARD_TEST_TENANT_ID?.trim();
const periodDays = Number(process.env.DASHBOARD_TEST_PERIOD_DAYS ?? 30);
const connectionUrl = process.env.DATABASE_URL;
const databaseName = connectionUrl
  ? decodeURIComponent(new URL(connectionUrl).pathname.slice(1))
  : "";

if (process.env.NODE_ENV === "production" || !/test|dev/i.test(databaseName)) {
  throw new Error(
    "Refusing to run: DATABASE_URL database name must contain TEST or DEV, and NODE_ENV must not be production."
  );
}
if (
  !tenantId ||
  !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
    tenantId
  )
) {
  throw new Error(
    "Set DASHBOARD_TEST_TENANT_ID to the UUID of the tenant whose dashboard you are testing."
  );
}
if (![7, 30, 90].includes(periodDays)) {
  throw new Error(
    "DASHBOARD_TEST_PERIOD_DAYS must be 7, 30, or 90 (default 30)."
  );
}
if (process.argv.slice(2).some((arg) => arg !== "--clean")) {
  throw new Error("The only supported argument is --clean.");
}

const clean = process.argv.includes("--clean");
const fixtureId = (key: string) => {
  const hash = createHash("sha256")
    .update(`ceopro-dashboard-metric-fixture-v1:${tenantId}:${key}`)
    .digest("hex");
  return `${hash.slice(0, 8)}-${hash.slice(8, 12)}-4${hash.slice(13, 16)}-a${hash.slice(17, 20)}-${hash.slice(20, 32)}`;
};

const invoices = [
  { key: "previous", number: `${marker}_PREVIOUS`, amount: 100 },
  { key: "current", number: `${marker}_CURRENT`, amount: 150 }
] as const;
const reviews = [
  { key: "review-one", score: 0.8, fraction: 1 / 3 },
  { key: "review-two", score: 0.6, fraction: 2 / 3 }
] as const;
const dayMs = 24 * 60 * 60 * 1000;
const today = new Date();
const currentEnd = new Date(
  Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() + 1)
);
const currentStart = new Date(currentEnd.getTime() - periodDays * dayMs);
const previousStart = new Date(currentStart.getTime() - periodDays * dayMs);
const atDay = (start: Date, offset: number) =>
  new Date(start.getTime() + offset * dayMs + 12 * 60 * 60 * 1000);

async function checkOwnership() {
  const existingInvoices = await prisma.invoices.findMany({
    where: {
      invoice_id: {
        in: invoices.map((item) => fixtureId(`invoice:${item.key}`))
      }
    }
  });
  for (const row of existingInvoices) {
    if (
      row.tenant_id !== tenantId ||
      !invoices.some(
        (item) =>
          row.invoice_id === fixtureId(`invoice:${item.key}`) &&
          row.invoice_number === item.number
      )
    ) {
      throw new Error(
        `Fixture invoice ID collision: ${row.invoice_id}. No rows were changed.`
      );
    }
  }
  const existingReviews = await prisma.reviews.findMany({
    where: { review_id: { in: reviews.map((item) => fixtureId(item.key)) } }
  });
  for (const row of existingReviews) {
    if (
      row.tenant_id !== tenantId ||
      row.source_platform !== marker ||
      !reviews.some(
        (item) =>
          row.review_id === fixtureId(item.key) &&
          row.external_review_id === `${marker}_${item.key}`
      )
    ) {
      throw new Error(
        `Fixture review ID collision: ${row.review_id}. No rows were changed.`
      );
    }
  }
}

async function main() {
  const company = await prisma.company.findUnique({ where: { id: tenantId! } });
  if (!company)
    throw new Error(
      "Tenant not found. Use the tenant ID shown by the account you are testing."
    );
  await checkOwnership();

  if (clean) {
    await prisma.$transaction(async (tx) => {
      const ownedInvoices = await tx.invoices.findMany({
        where: {
          tenant_id: tenantId!,
          invoice_number: { in: invoices.map((item) => item.number) },
          invoice_id: {
            in: invoices.map((item) => fixtureId(`invoice:${item.key}`))
          }
        },
        select: { invoice_id: true }
      });
      const ownedReviews = await tx.reviews.findMany({
        where: {
          tenant_id: tenantId!,
          source_platform: marker,
          review_id: { in: reviews.map((item) => fixtureId(item.key)) }
        },
        select: { review_id: true }
      });
      await tx.sentiment_results.deleteMany({
        where: {
          tenant_id: tenantId!,
          review_id: { in: ownedReviews.map((item) => item.review_id) }
        }
      });
      await tx.reviews.deleteMany({
        where: {
          tenant_id: tenantId!,
          review_id: { in: ownedReviews.map((item) => item.review_id) },
          source_platform: marker
        }
      });
      await tx.invoice_items.deleteMany({
        where: {
          tenant_id: tenantId!,
          invoice_id: { in: ownedInvoices.map((item) => item.invoice_id) }
        }
      });
      await tx.invoices.deleteMany({
        where: {
          tenant_id: tenantId!,
          invoice_id: { in: ownedInvoices.map((item) => item.invoice_id) },
          invoice_number: { in: invoices.map((item) => item.number) }
        }
      });
    });
    console.log(`Removed only ${marker} rows for tenant ${tenantId}.`);
    return;
  }

  const product = await prisma.products.findFirst({
    where: {
      tenant_id: tenantId!,
      currency: company.primaryCurrency,
      deleted_at: null
    },
    select: { product_id: true }
  });
  if (!product)
    throw new Error(
      `No active ${company.primaryCurrency} product exists for this tenant. No rows were changed.`
    );

  await prisma.$transaction(async (tx) => {
    for (const item of invoices) {
      const invoiceId = fixtureId(`invoice:${item.key}`);
      const sameNumber = await tx.invoices.findFirst({
        where: { tenant_id: tenantId!, invoice_number: item.number },
        select: { invoice_id: true }
      });
      if (sameNumber && sameNumber.invoice_id !== invoiceId)
        throw new Error(
          `Invoice number ${item.number} is already in use; transaction rolled back.`
        );
      const date = atDay(
        item.key === "previous" ? previousStart : currentStart,
        Math.floor(periodDays / 2)
      );
      const fields = {
        invoice_number: item.number,
        customer_name: "Dashboard metric test fixture",
        issue_date: date,
        created_at: date,
        currency: company.primaryCurrency,
        payment_status: "PAID",
        subtotal: item.amount,
        tax_amount: 0,
        total_amount: item.amount
      };
      await tx.invoices.upsert({
        where: { invoice_id: invoiceId },
        create: { invoice_id: invoiceId, tenant_id: tenantId!, ...fields },
        update: fields
      });
      const itemId = fixtureId(`invoice-item:${item.key}`);
      const oldItem = await tx.invoice_items.findUnique({
        where: { invoice_item_id: itemId }
      });
      if (
        oldItem &&
        (oldItem.tenant_id !== tenantId || oldItem.invoice_id !== invoiceId)
      )
        throw new Error("Invoice item ID collision; transaction rolled back.");
      const line = {
        product_id: product.product_id,
        quantity: 1,
        unit_price: item.amount,
        total_price: item.amount
      };
      await tx.invoice_items.upsert({
        where: { invoice_item_id: itemId },
        create: {
          invoice_item_id: itemId,
          tenant_id: tenantId!,
          invoice_id: invoiceId,
          ...line
        },
        update: line
      });
    }
    for (const item of reviews) {
      const reviewId = fixtureId(item.key);
      const date = atDay(
        currentStart,
        Math.max(1, Math.floor(periodDays * item.fraction))
      );
      const fields = {
        product_id: product.product_id,
        source_platform: marker,
        external_review_id: `${marker}_${item.key}`,
        reviewer_name: "Dashboard metric test fixture",
        review_text: "Test fixture: quality and service were excellent.",
        review_rating: 5,
        review_date: date,
        source_status: "ALLOWED",
        safety_status: "SAFE"
      };
      await tx.reviews.upsert({
        where: { review_id: reviewId },
        create: { review_id: reviewId, tenant_id: tenantId!, ...fields },
        update: fields
      });
      const sentimentId = fixtureId(`sentiment:${item.key}`);
      const oldSentiment = await tx.sentiment_results.findUnique({
        where: { review_id: reviewId }
      });
      const oldSentimentId = await tx.sentiment_results.findUnique({
        where: { sentiment_id: sentimentId }
      });
      if (
        (oldSentiment &&
          (oldSentiment.tenant_id !== tenantId ||
            oldSentiment.sentiment_id !== sentimentId)) ||
        (oldSentimentId &&
          (oldSentimentId.tenant_id !== tenantId ||
            oldSentimentId.review_id !== reviewId))
      ) {
        throw new Error("Review sentiment collision; transaction rolled back.");
      }
      const sentiment = {
        sentiment_score: item.score,
        sentiment_label: "POSITIVE",
        model_version: "fixture-dashboard-v1",
        processed_at: date
      };
      await tx.sentiment_results.upsert({
        where: { sentiment_id: sentimentId },
        create: {
          sentiment_id: sentimentId,
          tenant_id: tenantId!,
          review_id: reviewId,
          ...sentiment
        },
        update: sentiment
      });
    }
  });

  const baseInvoiceFilter = {
    tenant_id: tenantId!,
    currency: company.primaryCurrency,
    payment_status: "PAID"
  };
  const [previous, current, scored] = await Promise.all([
    prisma.invoices.aggregate({
      where: {
        ...baseInvoiceFilter,
        created_at: { gte: previousStart, lt: currentStart }
      },
      _sum: { total_amount: true },
      _count: true
    }),
    prisma.invoices.aggregate({
      where: {
        ...baseInvoiceFilter,
        created_at: { gte: currentStart, lt: currentEnd }
      },
      _sum: { total_amount: true },
      _count: true
    }),
    prisma.sentiment_results.aggregate({
      where: {
        tenant_id: tenantId!,
        reviews: {
          review_date: { gte: currentStart, lt: currentEnd },
          source_status: "ALLOWED",
          safety_status: "SAFE"
        }
      },
      _avg: { sentiment_score: true },
      _count: true
    })
  ]);
  const priorRevenue = Number(previous._sum.total_amount ?? 0);
  const currentRevenue = Number(current._sum.total_amount ?? 0);
  const score =
    scored._avg.sentiment_score == null
      ? null
      : Number(scored._avg.sentiment_score);
  const growth =
    priorRevenue > 0
      ? `${(((currentRevenue - priorRevenue) / priorRevenue) * 100).toFixed(1)}%`
      : "unavailable";
  const reviewSentiment =
    score == null
      ? "unavailable"
      : score > 0.1
        ? "positive"
        : score < -0.1
          ? "negative"
          : "neutral";
  console.log(
    JSON.stringify(
      {
        tenantId,
        company: company.businessName,
        currency: company.primaryCurrency,
        periodDays,
        previousStartUtc: previousStart.toISOString(),
        currentStartUtc: currentStart.toISOString(),
        currentEndExclusiveUtc: currentEnd.toISOString(),
        previousPaidInvoices: previous._count,
        previousRevenue: priorRevenue,
        currentPaidInvoices: current._count,
        currentRevenue,
        growth,
        scoredReviews: scored._count,
        averageReviewScore: score,
        reviewSentiment,
        note: "Totals include existing tenant rows. The fixture contributes 100 previous revenue, 150 current revenue, and two positive reviews."
      },
      null,
      2
    )
  );
}

main()
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
