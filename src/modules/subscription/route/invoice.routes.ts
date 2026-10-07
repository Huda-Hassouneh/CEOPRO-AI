import { Router } from "express";
import {
  authenticateUser,
  requireTenant
} from "../../../middleware/validators/validateUser.js";
import { getInvoicesHandler } from "../controller/invoice.controller.js";

const router = Router();

router.get("/invoices", authenticateUser, requireTenant, getInvoicesHandler);

export default router;
