import express from "express";
const app = express();

// global middlewares

app.get("/", (_req, res) => {
  res.json({ message: "API is running..." });
});

export default app;
