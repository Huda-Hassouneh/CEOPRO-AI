import { Router } from "express";
import { onBoardingHandler } from "../controllers/controller.js";
import {
  isAdmin,
  validateHeader,
  validateToken
} from "../../../validators/token.js";

const router = Router();

// global - route-scoped middlewares -
router.use(validateHeader, validateToken, isAdmin);

router.post("/on-boarding", onBoardingHandler);

export default { router };
