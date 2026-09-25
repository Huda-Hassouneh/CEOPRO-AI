import "dotenv/config";
import bcrypt from "bcryptjs";
import { generateAccessToken } from "../../src/utils/token.js";
import { prisma } from "../../src/config/database.js";

async function insertPermission() {
  const adminRole = await prisma.systemRole.findUnique({
    where: {
      roleKey: "admin"
    }
  });

  if (!adminRole) {
    throw new Error('System role "admin" does not exist in the database.');
  }

  const currentPermissions =
    adminRole.permissions &&
    typeof adminRole.permissions === "object" &&
    !Array.isArray(adminRole.permissions)
      ? adminRole.permissions
      : {};

  await prisma.systemRole.update({
    where: {
      roleKey: "admin"
    },
    data: {
      permissions: {
        ...currentPermissions,
        manage_billing: true
      }
    }
  });

  console.log('Ensured "manage_billing" permission exists for admin role.');
}

async function main() {
  insertPermission();
  const adminEmail = process.env.ADMIN_EMAIL;
  const adminPassword = process.env.ADMIN_PASSWORD;
  const adminFullName = process.env.ADMIN_FULL_NAME ?? "Administrator";

  const adminTenantId = process.env.ADMIN_TENANT_ID;

  const language = process.env.ADMIN_LANGUAGE ?? "en";

  // ---------------------------------------------------------
  // Validate env
  // ---------------------------------------------------------

  if (!adminEmail) {
    throw new Error("ADMIN_EMAIL environment variable is required.");
  }

  if (!adminPassword) {
    throw new Error("ADMIN_PASSWORD environment variable is required.");
  }

  if (!adminTenantId) {
    throw new Error("ADMIN_TENANT_ID environment variable is required.");
  }

  // ---------------------------------------------------------
  // Ensure admin role exists
  // ---------------------------------------------------------

  const adminRole = await prisma.systemRole.findUnique({
    where: {
      roleKey: "admin"
    }
  });

  if (!adminRole) {
    throw new Error('System role "admin" does not exist in the database.');
  }

  // ---------------------------------------------------------
  // Ensure tenant exists
  // ---------------------------------------------------------

  const tenant = await prisma.company.findUnique({
    where: {
      id: adminTenantId
    }
  });

  if (!tenant || tenant.deletedAt) {
    throw new Error(
      `Tenant "${adminTenantId}" does not exist or has been deleted.`
    );
  }

  // ---------------------------------------------------------
  // Bootstrap admin atomically
  // ---------------------------------------------------------

  const result = await prisma.$transaction(async (tx) => {
    // -------------------------------------------------------
    // User
    // -------------------------------------------------------

    let adminUser = await tx.user.findFirst({
      where: {
        email: adminEmail
      }
    });

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
      console.log(`Admin user already exists: ${adminEmail}`);
    }

    // -------------------------------------------------------
    // TenantUser
    // -------------------------------------------------------

    const tenantUser = await tx.tenantUser.upsert({
      where: {
        tenantId_userId: {
          tenantId: tenant.id,
          userId: adminUser.userId
        }
      },

      update: {
        roleKey: "admin",
        removedAt: null
      },

      create: {
        tenantId: tenant.id,
        userId: adminUser.userId,
        roleKey: "admin"
      }
    });

    return {
      user: adminUser,
      company: tenant,
      tenantUser
    };
  });

  // ---------------------------------------------------------
  // Generate admin access token
  // ---------------------------------------------------------

  const accessToken = generateAccessToken({
    id: result.user.userId,
    tenant_id: result.company.id,
    email: result.user.email,
    roleKey: result.tenantUser.roleKey
  });

  // ---------------------------------------------------------
  // Output
  // ---------------------------------------------------------

  console.log("");
  console.log("========================================");
  console.log("Admin bootstrap completed");
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
    await prisma.$disconnect();
  });
