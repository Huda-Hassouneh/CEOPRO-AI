import { prisma } from "../../../src/config/database.js";
import { catalog, companies, tenantBrands } from "../data/catalog.js";
import { inBatches } from "../helpers/batch.js";
import type { SeedClock } from "../helpers/time.js";

export async function seedCommerceData(args: {
  tenantIds: string[];
  users: Array<{ userId: string }>;
  uuid: (key: string) => string;
  clock: SeedClock;
}) {
  const { tenantIds, users, uuid, clock } = args;

  const products = companies.flatMap(([, , currency], tenantIndex) =>
    (tenantIndex === 4 ? catalog.slice(0, 5) : catalog).map(
      ([name, category, basePrice], productIndex) => ({
        product_id: uuid(`product:${tenantIndex}:${productIndex}`),
        tenant_id: tenantIds[tenantIndex],
        product_name: { en: name },
        category: { en: category },
        brand: { en: `${tenantBrands[tenantIndex]} Select` },
        current_price: +(
          basePrice * (1 + tenantIndex * 0.04) +
          (productIndex % 3)
        ).toFixed(2),
        cost_price: +(basePrice * 0.58).toFixed(2),
        currency,
        source: "MANUAL",
        created_at: clock.ago(180 - productIndex * 2),
        metadata: { fixture: "ceopro-v1" }
      })
    )
  );

  await inBatches(products, (batch) =>
    prisma.products.createMany({ data: batch, skipDuplicates: true })
  );

  const inventory = products.map((product, index) => ({
    tenant_id: product.tenant_id,
    product_id: product.product_id,
    inventory_id: uuid(`inventory:${index}`),
    stock_quantity:
      index % 17 === 0 ? 0 : index % 11 === 0 ? 4 : 60 + (index % 90),
    reorder_level: 12
  }));

  await inBatches(inventory, (batch) =>
    prisma.inventory.createMany({ data: batch, skipDuplicates: true })
  );

  await prisma.rag_documents_metadata.createMany({
    data: tenantIds.flatMap((tenant_id, tenantIndex) =>
      ["Pending", "Processed", "Failed"].map((processed_status, documentIndex) => ({
        document_id: uuid(`document:${tenantIndex}:${documentIndex}`),
        tenant_id,
        file_name: `${
          ["inventory-guide", "catalog-notes", "failed-import"][documentIndex]
        }.txt`,
        storage_bucket_path: `fixtures/ceopro-v1/${tenantIndex}/${documentIndex}.txt`,
        file_size_bytes: BigInt(1024 + documentIndex * 120),
        content_type: "text/plain",
        uploaded_by_user_id: users[tenantIndex * 5].userId,
        processed_status
      }))
    ),
    skipDuplicates: true
  });

  const transactions = products.flatMap((product, productIndex) =>
    Array.from(
      { length: productIndex % 13 === 0 ? 4 : 32 },
      (_, transactionIndex) => {
        const quantity_sold = 1 + ((transactionIndex + productIndex) % 5);
        const unit_price = Number(product.current_price);

        return {
          transaction_id: uuid(`sale:${productIndex}:${transactionIndex}`),
          tenant_id: product.tenant_id,
          product_id: product.product_id,
          quantity_sold,
          unit_price,
          total_price: +(quantity_sold * unit_price).toFixed(4),
          original_currency: product.currency,
          transaction_date: clock.ago(
            (transactionIndex * 11 + productIndex * 3) % 360
          ),
          sale_source: transactionIndex % 4 ? "POS" : "IMPORT"
        };
      }
    )
  );

  await inBatches(transactions, (batch) =>
    prisma.transactions.createMany({ data: batch, skipDuplicates: true })
  );

  const reviews = products.flatMap((product, productIndex) =>
    Array.from(
      { length: productIndex % 11 === 0 ? 1 : 8 },
      (_, reviewIndex) => {
        const rating = ((productIndex + reviewIndex) % 5) + 1;

        return {
          review_id: uuid(`review:${productIndex}:${reviewIndex}`),
          tenant_id: product.tenant_id,
          product_id: product.product_id,
          subject_type: "PRODUCT",
          source_platform: "DEMO_IMPORT",
          reviewer_name: `Demo customer ${reviewIndex + 1}`,
          review_text:
            rating >= 4
              ? "Reliable quality and prompt delivery."
              : rating <= 2
                ? "The product did not meet my expectations."
                : "Good overall, with room to improve packaging.",
          review_rating: rating,
          review_date: clock.ago((productIndex * 5 + reviewIndex * 9) % 240),
          source_status: "ALLOWED",
          collection_method: "MANUAL"
        };
      }
    )
  );

  await inBatches(reviews, (batch) =>
    prisma.reviews.createMany({ data: batch, skipDuplicates: true })
  );

  return { products, inventory, transactions, reviews };
}
