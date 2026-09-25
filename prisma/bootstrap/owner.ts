import "dotenv/config";
import bcrypt from "bcryptjs";
import { generateAccessToken } from "../../src/utils/token.js";

// CHANGE THIS IMPORT to match your generated Prisma client location.
import { prisma } from "../../src/config/database.js";

// CHANGE THIS PATH to your real auth utility path

async function main() {
  const ownerEmail = process.env.OWNER_EMAIL;
  const ownerPassword = process.env.OWNER_PASSWORD;
  const ownerFullName = process.env.OWNER_FULL_NAME ?? "Platform Owner";

  const companyName = process.env.OWNER_COMPANY_NAME ?? "CEO PRO Platform";

  const countryCode = process.env.OWNER_COUNTRY_CODE ?? "JO";

  const primaryCurrency = process.env.OWNER_PRIMARY_CURRENCY ?? "JOD";

  const timezone = process.env.OWNER_TIMEZONE ?? "Asia/Amman";

  const language = process.env.OWNER_LANGUAGE ?? "en";

  // ---------------------------------------------------------
  // Validate env
  // ---------------------------------------------------------

  if (!ownerEmail) {
    throw new Error("OWNER_EMAIL environment variable is required.");
  }

  if (!ownerPassword) {
    throw new Error("OWNER_PASSWORD environment variable is required.");
  }

  // ---------------------------------------------------------
  // Ensure owner role exists
  // ---------------------------------------------------------

  const ownerRole = await prisma.systemRole.findUnique({
    where: {
      roleKey: "owner",
    },
  });

  if (!ownerRole) {
    throw new Error('System role "owner" does not exist in the database.');
  }

  // ---------------------------------------------------------
  // Bootstrap owner atomically
  // ---------------------------------------------------------

  const result = await prisma.$transaction(async (tx) => {
    // -------------------------------------------------------
    // User
    // -------------------------------------------------------

    let ownerUser = await tx.user.findFirst({
      where: {
        email: ownerEmail,
      },
    });

    if (!ownerUser) {
      const passwordHash = await bcrypt.hash(ownerPassword, 12);

      ownerUser = await tx.user.create({
        data: {
          email: ownerEmail,
          passwordHash,
          fullName: ownerFullName,
          preferredLanguage: language,
        },
      });

      console.log(`Created owner user: ${ownerEmail}`);
    } else {
      console.log(`Owner user already exists: ${ownerEmail}`);
    }

    // -------------------------------------------------------
    // Existing owner membership
    // -------------------------------------------------------

    const existingOwnerMembership = await tx.tenantUser.findFirst({
      where: {
        userId: ownerUser.userId,
        roleKey: "owner",
        removedAt: null,
      },
      include: {
        tenant: true,
      },
    });

    if (existingOwnerMembership) {
      return {
        user: ownerUser,
        company: existingOwnerMembership.tenant,
        tenantUser: existingOwnerMembership,
      };
    }

    // -------------------------------------------------------
    // Platform company
    // -------------------------------------------------------

    let company = await tx.company.findFirst({
      where: {
        businessName: companyName,
        deletedAt: null,
      },
    });

    if (!company) {
      company = await tx.company.create({
        data: {
          businessName: companyName,
          businessType: "platform",
          countryCode,
          operatingCountries: [countryCode],
          primaryCurrency,
          supportedCurrencies: [primaryCurrency],
          timezone,
          preferredLanguage: language,
          supportedLanguages: [language],
        },
      });

      console.log(`Created platform company: ${company.businessName}`);
    } else {
      console.log(`Platform company already exists: ${company.businessName}`);
    }

    // -------------------------------------------------------
    // TenantUser
    // -------------------------------------------------------

    const tenantUser = await tx.tenantUser.upsert({
      where: {
        tenantId_userId: {
          tenantId: company.id,
          userId: ownerUser.userId,
        },
      },

      update: {
        roleKey: "owner",
        removedAt: null,
      },

      create: {
        tenantId: company.id,
        userId: ownerUser.userId,
        roleKey: "owner",
      },
    });

    return {
      user: ownerUser,
      company,
      tenantUser,
    };
  });

  // ---------------------------------------------------------
  // Generate owner access token
  // ---------------------------------------------------------

  const accessToken = generateAccessToken({
    id: result.user.userId,
    tenant_id: result.company.id,
    email: result.user.email,
    roleKey: result.tenantUser.roleKey,
  });

  // ---------------------------------------------------------
  // Output
  // ---------------------------------------------------------

  console.log("");
  console.log("========================================");
  console.log("Platform owner bootstrap completed");
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
    console.error("Owner bootstrap failed:");
    console.error(error);

    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
