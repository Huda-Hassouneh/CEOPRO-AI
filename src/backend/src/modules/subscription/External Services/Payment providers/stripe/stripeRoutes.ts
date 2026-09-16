import express from "express";
import validateWebhook from "../../../../../validators/webhook.js";
import { webhookHandler } from "./stripeController.js";
const router = express.Router();

router.post(
  "/",
  express.raw({ type: "application/json" }),
  validateWebhook,
  webhookHandler
);
export default { router };
