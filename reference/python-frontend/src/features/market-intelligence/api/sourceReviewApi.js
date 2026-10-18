import httpClient from '../../../shared/lib/httpClient.js';

// Wraps the real backend endpoints - backend/src/ai/routers/competitors.py's
// GET /competitors/sources and POST /competitors/sources/{source_id}/review,
// themselves a thin wrapper around source_review.py::review_source(). A
// fully automated discovery run never has real Terms-of-Service evidence,
// so policy.py::evaluate_source() correctly leaves every discovered source
// RESTRICTED (or BLOCKED) - never ALLOWED - until a real owner/admin
// reviews it here. This is that missing review step, reachable from the
// product itself instead of only a CLI an operator would have to run.
export const sourceReviewApi = {
  listSources: async ({ status, limit, offset } = {}) => {
    const response = await httpClient.get('/competitors/sources', { params: { status, limit, offset } });
    return response.data;
  },

  // Owner/admin only server-side (a 403 from a non-admin caller surfaces
  // as a real error, not silently ignored) - same authorization tier as
  // the company-wide search-scope settings.
  reviewSource: async (sourceId, { termsPermit, reviewerReference }) => {
    const response = await httpClient.post(`/competitors/sources/${sourceId}/review`, {
      terms_permit: termsPermit,
      reviewer_reference: reviewerReference,
    });
    return response.data;
  },
};
