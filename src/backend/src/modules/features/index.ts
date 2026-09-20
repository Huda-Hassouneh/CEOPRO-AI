import { Router } from "express";
import featuresRoutes from "./routes/features-managment.route.js";
import planFeaturesRoutes from "./routes/feature-plan.js";

const router = Router();

// 1. Mount core features
router.use("/features", featuresRoutes);

router.use("/", planFeaturesRoutes);

export default router;
