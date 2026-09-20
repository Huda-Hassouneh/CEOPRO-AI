import { Router } from "express";
import {
  authenticateUser,
  requireTenant
} from "../../../validators/validateUser.js";
import { getInvoicesHandler } from "../controllers/invoice.controller.js";

const router = Router();

router.get("/invoices", authenticateUser, requireTenant, getInvoicesHandler);

export default router;
