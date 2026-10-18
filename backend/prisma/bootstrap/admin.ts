import "dotenv/config";
import bcrypt from "bcryptjs";
import { generateAccessToken } from "../../src/utils/token.js";
import { prisma } from "../../src/config/database.js";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function requiredEnv(name: string): string {
  const value = process.env[name]?.trim();

  if (!value) {
    throw new Error(`${name} environment variable is required.`);
  }

  return value;
}

async function main() {
  const adminEmail = requiredEnv("ADMIN_EMAIL").toLowerCase();
  const adminPassword = requiredEnv("ADMIN_PASSWORD");
  const adminTenantId = requiredEnv("ADMIN_TENANT_ID");

  const adminFullName = process.env.ADMIN_FULL_NAME?.trim() || "Administrator";
  const language = process.env.ADMIN_LANGUAGE?.trim() || "en";

  // These values are used only when ADMIN_TENANT_ID does not exist yet.
  const tenantName = process.env.ADMIN_TENANT_NAME?.trim();
  const tenantCountryCode =
    process.env.ADMIN_TENANT_COUNTRY_CODE?.trim().toUpperCase() || "JO";
  const tenantPrimaryCurrency =
    process.env.ADMIN_TENANT_PRIMARY_CURRENCY?.trim().toUpperCase() || "USD";
  const tenantTimezone =
    process.env.ADMIN_TENANT_TIMEZONE?.trim() || "Asia/Amman";
  const tenantLanguage = process.env.ADMIN_TENANT_LANGUAGE?.trim() || language;

  if (!UUID_PATTERN.test(adminTenantId)) {
    throw new Error("ADMIN_TENANT_ID must be a valid UUID.");
  }

  if (tenantCountryCode.length !== 2) {
    throw new Error(
      "ADMIN_TENANT_COUNTRY_CODE must be a 2-letter country code."
    );
  }

  if (tenantPrimaryCurrency.length !== 3) {
    throw new Error(
      "ADMIN_TENANT_PRIMARY_CURRENCY must be a 3-letter currency code."
    );
  }

  const result = await prisma.$transaction(async (tx) => {
    // Ensure admin role exists
    const adminRole = await tx.systemRole.findUnique({
      where: {
        roleKey: "admin"
      }
    });

    if (!adminRole) {
      throw new Error(
        'System role "admin" does not exist in the database. Run the role/bootstrap migrations before bootstrapping an admin.'
      );
    }

    // Ensure platform tenant exists
    let tenant = await tx.company.findUnique({
      where: {
        id: adminTenantId
      }
    });

    if (!tenant) {
      if (!tenantName) {
        throw new Error(
          `Tenant "${adminTenantId}" does not exist. Set ADMIN_TENANT_NAME so bootstrap:admin can create it.`
        );
      }

      tenant = await tx.company.create({
        data: {
          id: adminTenantId,
          businessName: tenantName,
          businessType: "platform",
          countryCode: tenantCountryCode,
          operatingCountries: [tenantCountryCode],
          primaryCurrency: tenantPrimaryCurrency,
          supportedCurrencies: [tenantPrimaryCurrency],
          timezone: tenantTimezone,
          preferredLanguage: tenantLanguage,
          supportedLanguages: [tenantLanguage],
          platformStatus: "active"
        }
      });

      console.log(
        `Created platform tenant: ${tenant.businessName} (${tenant.id})`
      );
    } else {
      if (tenant.deletedAt) {
        throw new Error(
          `Tenant "${adminTenantId}" exists but has been deleted. The bootstrap will not silently restore a deleted tenant.`
        );
      }

      if (tenant.businessType !== "platform") {
        throw new Error(
          `Tenant "${adminTenantId}" exists with businessType "${tenant.businessType ?? "null"}". Platform admins must belong to a platform tenant.`
        );
      }

      if (tenant.platformStatus !== "active") {
        throw new Error(
          `Tenant "${adminTenantId}" exists but platformStatus is "${tenant.platformStatus}". Activate it explicitly before bootstrapping an admin.`
        );
      }

      console.log(
        `Platform tenant already exists: ${tenant.businessName} (${tenant.id})`
      );
    }

    // Ensure admin user exists
    const matchingUsers = await tx.user.findMany({
      where: {
        email: {
          equals: adminEmail,
          mode: "insensitive"
        }
      },
      take: 2
    });

    if (matchingUsers.length > 1) {
      throw new Error(
        `More than one user exists with email "${adminEmail}". Resolve the duplicate users before running the admin bootstrap.`
      );
    }

    let adminUser = matchingUsers[0];

    if (!adminUser) {
      const passwordHash = await bcrypt.hash(adminPassword, 12);

      adminUser = await tx.user.create({
        data: {
          email: adminEmail,
          passwordHash,
          fullName: adminFullName,
          preferredLanguage: language
        }
      });

      console.log(`Created admin user: ${adminEmail}`);
    } else {
      console.log(
        `Admin user already exists: ${adminUser.email}. Existing password was preserved.`
      );
    }

    // Ensure admin membership exists
    const existingMembership = await tx.tenantUser.findUnique({
      where: {
        tenantId_userId: {
          tenantId: tenant.id,
          userId: adminUser.userId
        }
      }
    });

    if (
      existingMembership &&
      existingMembership.removedAt === null &&
      existingMembership.roleKey === "owner"
    ) {
      throw new Error(
        `User "${adminUser.email}" is already an active owner of platform tenant "${tenant.id}". The bootstrap will not demote an owner to admin.`
      );
    }

    const tenantUser = await tx.tenantUser.upsert({
      where: {
        tenantId_userId: {
          tenantId: tenant.id,
          userId: adminUser.userId
        }
      },

      update: {
        roleKey: "admin",
        removedAt: null,
        platformStatus: "active"
      },

      create: {
        tenantId: tenant.id,
        userId: adminUser.userId,
        roleKey: "admin",
        platformStatus: "active"
      }
    });

    return {
      user: adminUser,
      company: tenant,
      tenantUser
    };
  });

  // Generate admin access token
  const accessToken = generateAccessToken({
    user_id: result.user.userId,
    id: result.user.userId,
    tenant_id: result.company.id,
    email: result.user.email,
    roleKey: result.tenantUser.roleKey
  });

  // Output logs
  console.log("");
  console.log("========================================");
  console.log("Platform admin bootstrap completed");
  console.log("========================================");

  console.log(`User ID:   ${result.user.userId}`);
  console.log(`Email:     ${result.user.email}`);
  console.log(`Tenant ID: ${result.company.id}`);
  console.log(`Company:   ${result.company.businessName}`);
  console.log(`Role:      ${result.tenantUser.roleKey}`);

  console.log("");
  console.log("Access Token:");
  console.log(accessToken);

  console.log("========================================");
}

main()
  .catch((error) => {
    console.error("");
    console.error("Admin bootstrap failed:");
    console.error(error);

    process.exit(1);
  })
  .finally(async () => {
    // close the connection .
    await prisma.$disconnect();
  });
