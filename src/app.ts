import express from "express";
import cors from "cors";
import { getCorsOrigins } from "./config/env.js";
import subscriptionModuleRouter, {
  stripeWebhookRouter as stripeRouter
} from "./modules/subscription/index.js";
import dashboard from "./modules/dashboard/index.js";
import marketInt from "./modules/market-intelligence/index.js";
import competitors from "./modules/competitors/index.js";
import dataconnection from "./modules/dataconnection/index.js";
import forecasting from "./modules/forecasting/index.js";
import pricing from "./modules/pricing/index.js";
import sentiment from "./modules/sentiment/index.js";
import mpi from "./modules/mpi/index.js";
import leaderboard from "./modules/opportunities/index.js";
import featureModuleRouter from "./modules/features/index.js";
import platformAdminRouter from "./modules/platform-admin/index.js";
import authRouter from "./modules/auth/index.js";
import onboardingRouter from "./modules/onboarding/index.js";
import {
  globalErrorHandler,
  notFoundHandler
} from "./middleware/errorHandler.js";
import { updateSubscriptionCancellation } from "./modules/subscription/External Services/Payment providers/stripe/stripeService.js";
// import "../scripts/generate-mock-token.js";
// updateSubscriptionCancellation("sub_1UMRxSDvEnSheKucIGd81uTd", false, true);

const app = express();
app.disable("x-powered-by");

const allowedOrigins = new Set(getCorsOrigins());
app.use(
  cors({
    origin(origin, callback) {
      if (!origin || allowedOrigins.has(origin)) return callback(null, true);
      return callback(new Error("Origin is not allowed by CORS"));
    },
    methods: ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allowedHeaders: ["Content-Type", "Authorization"]
  })
);
// Stripe webhook must receive the untouched raw body before JSON parsing.
app.use("/stripe/webhooks", stripeRouter);
app.use((_req, res, next) => {
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("Referrer-Policy", "no-referrer");
  res.setHeader("X-Frame-Options", "DENY");
  next();
});

app.use(express.json({ limit: process.env.JSON_BODY_LIMIT || "1mb" }));

app.use("/auth", authRouter);
app.use("/onboarding", onboardingRouter);
app.use("/platform-admin", platformAdminRouter);
app.use("/subscription", subscriptionModuleRouter);
app.use("/features/pricing", pricing);
app.use("/features/sentiment", sentiment);
app.use("/features/mpi", mpi);
app.use("/", featureModuleRouter);
app.use("/", dashboard);
app.use("/", forecasting);
app.use("/", dataconnection);
app.use("/", marketInt);
app.use("/competitors", competitors);
app.use("/leaderboard", leaderboard);

app.get("/", (_req, res) => {
  res.json({ message: "CEO PRO API is running..." });
});

app.use(notFoundHandler);
app.use(globalErrorHandler);

export default app;
