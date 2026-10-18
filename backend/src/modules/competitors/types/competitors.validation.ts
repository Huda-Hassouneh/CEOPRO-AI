import { z } from "zod";
export function websiteIdentity(value: string) {
  const url = new URL(value);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || !url.hostname.includes('.')) throw new Error('Invalid website');
  // Preserve paths: different marketplace stores on one host are different businesses.
  return url.hostname.toLowerCase().replace(/^www\./, '') + (url.port ? ':' + url.port : '') + url.pathname.replace(/\/+$/, '');
}
const website = z.string().trim().max(2048).refine(value => { try { websiteIdentity(value); return true; } catch { return false; } }, 'Use a public HTTP or HTTPS website without credentials.');
export const competitorCreateSchema = z.object({ name: z.string().trim().min(1).max(255), website, industry: z.string().trim().max(150).optional() }).strict();
export const competitorUpdateSchema = z.object({ alias: z.string().trim().max(255).nullable() }).strict();
export const competitorTrackingSchema = z.object({ isTracked: z.boolean() }).strict();
export const mappingConfirmationSchema = z.object({ comparisonConfirmed: z.boolean() }).strict();
export const competitorListSchema = z.object({ status: z.enum(['active', 'inactive', 'all']).default('active') });
export type CompetitorCreate = z.infer<typeof competitorCreateSchema>;

// Clients attest terms/privacy; technical permission and reviewer identity are server-owned.
export const sourceReviewSchema = z.object({
  termsPermit: z.boolean(),
  reference: z.string().trim().min(10).max(2000),
  privacyReviewed: z.boolean(),
  retentionDays: z.number().int().min(1).max(90),
  containsPersonalData: z.boolean(),
  rateLimitPerMinute: z.number().int().min(1).max(30)
}).strict().refine(value => !value.termsPermit || value.privacyReviewed, {message:'Review privacy before approving collection.',path:['privacyReviewed']});
export type SourceReview = z.infer<typeof sourceReviewSchema>;

export const collectionRetrySchema=z.object({failedEventId:z.string().uuid()}).strict();
export const productLinkSchema=z.object({productId:z.string().uuid(),url:website,expectedMappingId:z.string().uuid().nullable()}).strict();
export type ProductLink=z.infer<typeof productLinkSchema>;
export const candidateDecisionSchema=z.object({rejected:z.literal(true)}).strict();
export const catalogSearchSchema=z.object({search:z.string().trim().max(150).default(''),page:z.coerce.number().int().min(1).max(100000).default(1)}).strict();
