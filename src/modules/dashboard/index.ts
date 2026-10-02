import { Router } from "express";
import dashboardRoutes from "./route/dashboard.route.js";

const router = Router();

// 1. Mount core features
router.use("/companies/:companyId/dashboard", dashboardRoutes);
export default router;
