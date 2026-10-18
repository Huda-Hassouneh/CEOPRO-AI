import { Router } from "express";
import forecastingRoutes from "./route/forecasting.route.js";

const router = Router();

// 1. Mount core features
router.use(`/forecasting`, forecastingRoutes);
export default router;
