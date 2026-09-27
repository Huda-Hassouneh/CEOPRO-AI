import { Router } from "express";
import * as c from "../controller/owner.controller.js";

// Mounted below authenticateUser, requireTenant and requirePlatformRole.
const router = Router();
router.get("/overview", c.permission("platform.overview.read"), c.readOverview);
router.get("/companies", c.permission("companies.read"), c.readCompanies);
router.get("/companies/:id", c.permission("companies.read"), c.readCompany);
router.post("/companies/:id/metadata", c.permission("companies.update"), c.companyMetadata);
router.post("/companies/:id/status", c.permission("companies.status.manage"), c.companyStatus);

router.get("/users", c.permission("users.read"), c.readUsers);
router.get("/users/:id", c.permission("users.read"), c.readUser);
router.post("/users/:id/status", c.permission("users.manage"), c.userStatus);

router.get("/admin-team", c.permission("adminTeam.read"), c.readTeam);
router.post("/admin-team/new/invite", c.permission("adminTeam.invite"), c.teamInvite);
router.post("/admin-team/:id/role", c.permission("adminTeam.roles.manage"), c.teamRole);
router.post("/admin-team/:id/status", c.permission("adminTeam.roles.manage"), c.teamStatus);
router.post("/admin-team/:id/remove", c.permission("adminTeam.remove"), c.teamRemove);
router.post("/admin-team/:id/resend", c.permission("adminTeam.invite"), c.teamResend);
router.post("/admin-team/:id/cancel", c.permission("adminTeam.remove"), c.teamCancel);

router.get("/audit-logs", c.permission("auditLogs.read"), c.readAudit);
router.get("/settings", c.permission("platformSettings.read"), c.readSettings);
router.post("/settings/new/update", c.permission("platformSettings.manage"), c.settingsUpdate);
router.get("/me/sessions", c.accountSessions);
router.post("/me/profile", c.accountProfile);
router.post("/me/password", c.accountPassword);
router.post("/me/revoke", c.accountRevoke);
router.post("/me/revokeOthers", c.accountRevokeOthers);

export default router;
