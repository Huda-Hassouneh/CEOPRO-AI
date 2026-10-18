import { Router } from "express";
import marketInt from "./route/market-int.route.js";

const router = Router();

// 1. Mount core features
router.use(`/market-intelligence`, marketInt);
export default router;
