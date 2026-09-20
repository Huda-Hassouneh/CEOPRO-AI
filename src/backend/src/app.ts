import express from "express";
import cors from "cors";
import "./mock/mock-user.js";

// Routers
import subscriptionModuleRouter from "./modules/subscription/index.js";
import featureModuleRouter from "./modules/features/index.js";
import stripeRouter from "./modules/subscription/External Services/Payment providers/stripe/stripeRoutes.js";

const app = express();

// ==========================================
// Global Middlewares
// ==========================================
app.use(
  cors({
    origin: "http://localhost:5173",
    methods: ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allowedHeaders: ["Content-Type", "Authorization"]
  })
);

// ==========================================
// Webhooks (Must precede express.json)
// ==========================================
app.use("/stripe/webhooks", stripeRouter);

// ==========================================
// Parsers
// ==========================================
app.use(express.json());

// ==========================================
// Module Routes
// ==========================================
app.use("/subscription", subscriptionModuleRouter);
app.use("/", featureModuleRouter);

// Health check
app.get("/", (_req, res) => {
  res.json({ message: "CEO PRO API is running..." });
});

export default app;
