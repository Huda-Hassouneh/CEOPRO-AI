import { Router } from "express";
import featuresRoutes from "./route/features-management.route.js";
import planFeaturesRoutes from "./route/feature-plan.route.js";
import featureOperationRoutes from "./route/features.route.js";

const router = Router();

// 1. Mount core features
router.use("/features", featureOperationRoutes);
router.use("/features", featuresRoutes);

router.use("/", planFeaturesRoutes);

export default router;
