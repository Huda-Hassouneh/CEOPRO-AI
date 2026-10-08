import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (path) => readFileSync(new URL(`../../${path}`, import.meta.url), "utf8");
const app = read("src/app.ts");
const authRoute = read("src/modules/auth/route/auth.route.ts");
const authRepo = read("src/modules/auth/repo/auth.repo.ts");
const authRlsMigration = read("prisma/migrations/20261008020000_auth_rls_login_lookup/migration.sql");
const scopedLoginMigration = read("prisma/migrations/20261008040000_scoped_auth_login_memberships/migration.sql");
const signupCompanyRlsMigration = read("prisma/migrations/20261008030000_auth_signup_company_rls/migration.sql");
const onboardingRoute = read("src/modules/onboarding/route/onboarding.route.ts");
const onboardingRepo = read("src/modules/onboarding/repo/onboarding.repo.ts");
const authService = read("src/modules/auth/service/auth.service.ts");
const authController = read("src/modules/auth/controller/auth.controller.ts");
const emailClient = read("src/integrations/email/resend.client.ts");
const emailService = read("src/integrations/email/email.service.ts");
const authMiddleware = read("src/middleware/validators/validateUser.ts");
const schema = read("prisma/schema.prisma");
const migration = read("prisma/migrations/20261005000000_add_onboarding/migration.sql");

const checks = [
  ["auth and tenant onboarding routers are mounted", app.includes('app.use("/auth", authRouter)') && app.includes('app.use("/onboarding", onboardingRouter)')],
  ["login verifies the password before loading scoped active memberships and keeps owner/customer membership selection", authRoute.includes("authRepo.findUserByEmail(email)") && authRoute.includes("verifyPassword(password, user.passwordHash)") && authRoute.indexOf("verifyPassword(password, user.passwordHash)") < authRoute.indexOf("authRepo.findLoginMemberships(user.userId, email)") && authRoute.includes("selectLoginMembership(memberships)") && authRepo.includes("set_config('app.auth_email'") && authRepo.includes("set_config('app.current_user_id'")],
  ["login removes broad tenant/company policies and grants only a context-checked function owned by a dedicated non-login role", authRlsMigration.includes("users_auth_email_lookup") && scopedLoginMigration.includes("DROP POLICY IF EXISTS tenant_users_auth_login_lookup") && scopedLoginMigration.includes("DROP POLICY IF EXISTS companies_auth_login_lookup") && scopedLoginMigration.includes("SECURITY DEFINER") && scopedLoginMigration.includes("SET search_path = pg_catalog, public") && scopedLoginMigration.includes("CREATE ROLE ceopro_auth_lookup") && scopedLoginMigration.includes("NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS") && scopedLoginMigration.includes("ALTER FUNCTION public.auth_login_memberships(uuid) OWNER TO ceopro_auth_lookup") && scopedLoginMigration.includes("p_user_id = NULLIF(current_setting('app.current_user_id'") && scopedLoginMigration.includes("lower(u.email) = lower(NULLIF(current_setting('app.auth_email'") && scopedLoginMigration.includes("REVOKE ALL ON FUNCTION public.auth_login_memberships(uuid) FROM PUBLIC") && scopedLoginMigration.includes("GRANT EXECUTE ON FUNCTION public.auth_login_memberships(uuid) TO ceopro_app")],
  ["signup sets user and tenant context before Prisma creates company rows and company RLS permits only that signup row to be returned", authRepo.includes("const tenantId = randomUUID()") && authRepo.indexOf("set_config('app.current_tenant_id'") < authRepo.indexOf("tx.company.create") && authRepo.includes("id: tenantId") && signupCompanyRlsMigration.includes("companies_auth_signup_returning") && signupCompanyRlsMigration.includes("TO ceopro_app") && signupCompanyRlsMigration.includes("app.current_user_id")],
  ["verification code exchange sets RLS context before loading the related user and rolls back incomplete grants", authRepo.includes("select: { userId: true, tenantId: true }") && authRepo.indexOf("set_config('app.current_tenant_id'", authRepo.indexOf("export async function consumeEmailVerificationGrant")) < authRepo.indexOf("tx.user.findUnique", authRepo.indexOf("export async function consumeEmailVerificationGrant")) && authRepo.includes("if (!user) throw new InvalidEmailVerificationGrantError()")],
  ["signup verification and one-time session exchange routes are present", authRoute.includes('"/register"') && authRoute.includes('"/verification/resend"') && authRoute.includes('"/verify-email/confirm"') && authRoute.includes('"/verification/exchange"')],
  ["signup does not create a user or session before email verification", authService.includes("createPendingSignup") && authService.includes("createAccountFromVerifiedSignup") && !authService.slice(authService.indexOf("export async function register"), authService.indexOf("export async function resendVerification")).includes("createUserWithCompany") && !authService.slice(authService.indexOf("export async function register"), authService.indexOf("export async function resendVerification")).includes("issueSession")],
  ["verification delivery can select Gmail SMTP or Resend and redirects to frontend onboarding", emailClient.includes("https://api.resend.com/emails") && emailClient.includes("EMAIL_SERVICE_PROVIDER_API_KEY") && emailService.includes('gmail_smtp: sendVerificationEmailWithGmail') && emailService.includes('resend: sendWithResend') && authService.includes("integrations/email/email.service.js") && authController.includes('destination.searchParams.set("code"')],
  ["profile and password routes remain present", authRoute.includes('router.get("/me"') && authRoute.includes('router.post(\n  "/change-password"')],
  ["protected requests reject revoked or expired persisted sessions", authMiddleware.includes("prisma.authSession.findFirst") && authMiddleware.includes("revokedAt: null") && authMiddleware.includes("expiresAt: { gt: new Date() }")],
  ["onboarding endpoints are behind authentication and tenant membership", onboardingRoute.indexOf("router.use(authenticateUser, requireTenant)") >= 0 && onboardingRoute.indexOf("router.use(authenticateUser, requireTenant)") < onboardingRoute.indexOf('router.get("/state"')],
  ["onboarding route exposes the complete wizard flow", ["/state", "/regional-preferences", "/profile", "/goals", "/plan", "/complete"].every((path) => onboardingRoute.includes(path))],
  ["onboarding persistence establishes tenant and user RLS context", onboardingRepo.includes("set_config('app.current_tenant_id'") && onboardingRepo.includes("set_config('app.current_user_id'")],
  ["onboarding model and migration include forced row-level security", schema.includes("model Onboarding {") && migration.includes("ALTER TABLE onboarding FORCE ROW LEVEL SECURITY") && migration.includes("tenant_isolation_onboarding")],
  ["pending signup and one-time verification grant models have a migration", schema.includes("model PendingSignup {") && schema.includes("model EmailVerificationGrant {") && read("prisma/migrations/20261007000000_email_verification_before_signup/migration.sql").includes("CREATE TABLE pending_signups")]
];

let failures = 0;
for (const [name, pass] of checks) {
  if (pass) console.log(`PASS: ${name}`);
  else {
    failures++;
    console.error(`FAIL: ${name}`);
  }
}

assert.equal(failures, 0, `${failures} auth/onboarding route contract check(s) failed`);
