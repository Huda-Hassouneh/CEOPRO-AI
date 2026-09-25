import express from "express";
import cors from "cors";
import { getCorsOrigins } from "./config/env.js";
import subscriptionModuleRouter from "./modules/subscription/index.js";
import featureModuleRouter from "./modules/features/index.js";
import platformAdminRouter from "./modules/platform-admin/platform-admin.routes.js";
import stripeRouter from "./modules/subscription/External Services/Payment providers/stripe/stripeRoutes.js";
import {
  globalErrorHandler,
  notFoundHandler,
} from "./middleware/errorHandler.js";
// import "../scripts/generate-mock-token.js";

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
    allowedHeaders: ["Content-Type", "Authorization"],
  }),
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

app.use("/platform-admin", platformAdminRouter);
app.use("/subscription", subscriptionModuleRouter);
app.use("/", featureModuleRouter);

app.get("/", (_req, res) => {
  res.json({ message: "CEO PRO API is running..." });
});

app.use(notFoundHandler);
app.use(globalErrorHandler);

export default app;
