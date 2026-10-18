import type { Request } from "express";
import type { JwtPayload } from "jsonwebtoken";
import type Stripe from "stripe";

export type AuthenticatedUser = JwtPayload & {
  user_id?: string;
  id: string;
  email: string;
  tenant_id?: string;
  /** Canonical role key from TenantUser/SystemRole (for example: owner, admin). */
  roleKey: string;
};

export interface AppRequest extends Request {
  user?: AuthenticatedUser;
  tenant_id?: string;
  tenantUser?: {
    roleKey: string;
    role?: {
      permissions: unknown;
    } | null;
    tenant?: {
      businessType: string | null;
    } | null;
  } | null;
  stripeEvent?: Stripe.Event;
}
