import { Router } from "express";
import dataconnection from "./route/dataconnection.route.js";

const router = Router();

// 1. Mount core features
router.use("/data-connection", dataconnection);
export default router;
