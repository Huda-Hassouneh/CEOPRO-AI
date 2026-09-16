import express from "express";
import promocodeRouter from "./modules/subscription/route/promocode.route.js";
import plansRouter from "./modules/subscription/route/plans.route.js";
import promocodesPlansRouter from "./modules/subscription/route/pomocodes-plans.route.js";
import subscriptionRouter from "./modules/subscription/route/subscription.route.js";
import stripeRouter from "./modules/subscription/External Services/Payment providers/stripe/stripeRoutes.js";
const app = express();

// global middlewares

// it must register before express.json() becouse stripe-signature-verification requires the raw request body.
app.use("/stripe/webhooks", stripeRouter.router);
app.use(express.json());
app.use("/subscription", promocodeRouter.router);
app.use("/subscription", plansRouter.router);
app.use("/subscription", promocodesPlansRouter.router);
app.use("/subscription", subscriptionRouter.router);
app.use("/subscription", promocodeRouter.router);

app.get("/", (_req, res) => {
  res.json({ message: "API is running..." });
});

export default app;
