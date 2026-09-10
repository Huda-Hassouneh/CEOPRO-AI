import express from "express";
import promoRouter from "./modules/subscription/routes.js";
const app = express();

// global middlewares
app.use(express.json());
app.use("/subscription", promoRouter.router);

app.get("/", (_req, res) => {
  res.json({ message: "API is running..." });
});

export default app;
