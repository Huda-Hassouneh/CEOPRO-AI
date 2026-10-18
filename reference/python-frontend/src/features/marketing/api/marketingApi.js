import httpClient from '../../../shared/lib/httpClient.js';

// The real backend endpoints - backend/src/ai/routers/marketing.py's
// GET /marketing/options, POST/GET /marketing/campaigns,
// GET /marketing/campaigns/{id}, POST /marketing/campaigns/{id}/image,
// POST /marketing/campaigns/{id}/generate-image,
// POST /marketing/campaigns/{id}/remove-background,
// POST /marketing/campaigns/{id}/reference-selection,
// GET /marketing/campaigns/{id}/image?kind=source|processed|generated.

export const marketingApi = {
  getOptions: async () => {
    const response = await httpClient.get('/marketing/options');
    return response.data;
  },

  listCampaigns: async ({ limit, offset, q } = {}) => {
    const response = await httpClient.get('/marketing/campaigns', { params: { limit, offset, q: q || undefined } });
    return response.data;
  },

  getCampaign: async (campaignId) => {
    const response = await httpClient.get(`/marketing/campaigns/${encodeURIComponent(campaignId)}`);
    return response.data;
  },

  // Exactly one of productId/text/url is sent - the backend rejects
  // (422) zero or more than one. creativeTheme omitted entirely lets the
  // backend recommend one; customCreativePrompt is only meaningful when
  // creativeTheme is 'CUSTOM' (or as extra instructions layered on a
  // named theme).
  createCampaign: async ({
    productId, text, url, style, tone, focus, strategyType, variantsPerPlatform,
    creativeTheme, customCreativePrompt, requestKey, generateImage, language, platforms,
  }) => {
    const payload = {
      product_id: productId || undefined,
      text: text || undefined,
      url: url || undefined,
      style: style || undefined,
      tone: tone || undefined,
      focus: focus || undefined,
      strategy_type: strategyType || undefined,
      variants_per_platform: variantsPerPlatform || undefined,
      platforms: platforms?.length ? platforms : undefined,
      creative_theme: creativeTheme || undefined,
      custom_creative_prompt: customCreativePrompt || undefined,
      // Same key for a repeated press -> the same campaign, never a second.
      request_key: requestKey || undefined,
      generate_image: generateImage || undefined,
    };
    // The copy is written in the language asked for, which can differ from the screen's.
    const response = await httpClient.post('/marketing/campaigns', payload, language ? { headers: { 'X-App-Language': language } } : undefined);
    return response.data;
  },

  // Saves edits to the title, audience note and copy variants.
  updateCampaign: async (campaignId, { title, audienceSummary, variants } = {}) => {
    const response = await httpClient.patch(`/marketing/campaigns/${encodeURIComponent(campaignId)}`, {
      title: title || undefined, audience_summary: audienceSummary ?? undefined, variants: variants || [],
    });
    return response.data;
  },

  deleteCampaign: async (campaignId) => (await httpClient.delete(`/marketing/campaigns/${encodeURIComponent(campaignId)}`)).data,

  uploadCampaignImage: async ({ campaignId, file }) => {
    const formData = new FormData();
    formData.append('file', file);
    // 'Content-Type': undefined (not a fixed string) - lets axios set the
    // multipart boundary itself from the FormData object, same convention
    // as ingestionApi.js::prepareFiles().
    const response = await httpClient.post(
      `/marketing/campaigns/${encodeURIComponent(campaignId)}/image`,
      formData,
      { headers: { 'Content-Type': undefined } },
    );
    return response.data;
  },

  // Always resolves 200 - the response body's image_generation_status is
  // the real outcome ('COMPLETED' / 'NOT_CONFIGURED' / 'PROVIDER_ERROR'),
  // never inferred from the HTTP status. See routers/marketing.py's own
  // generate_campaign_image_endpoint() docstring for why.
  generateImage: async (campaignId) => {
    const response = await httpClient.post(`/marketing/campaigns/${encodeURIComponent(campaignId)}/generate-image`);
    return response.data;
  },

  // Blob + object URL, same pattern as ingestionApi.js::downloadTemplate -
  // goes through this authenticated API (never a direct MinIO URL) so the
  // same tenant-scoped auth boundary as every other endpoint applies.
  // Caller owns revoking the returned URL (URL.revokeObjectURL) once done
  // with it.
  getCampaignImageBlob: async (campaignId, kind = 'generated') => {
    const response = await httpClient.get(
      `/marketing/campaigns/${encodeURIComponent(campaignId)}/image`,
      { params: { kind }, responseType: 'blob' },
    );
    return response.data;
  },

  getCampaignImage: async (campaignId, kind = 'generated') => URL.createObjectURL(await marketingApi.getCampaignImageBlob(campaignId, kind)),

  // Always resolves 200 - the response body's background_removal_status
  // is the real outcome ('COMPLETED' / 'NOT_CONFIGURED' / 'PROVIDER_ERROR'),
  // same convention as generateImage above. Operates on the campaign's
  // already-uploaded source image; never modifies/deletes it.
  removeBackground: async (campaignId) => {
    const response = await httpClient.post(`/marketing/campaigns/${encodeURIComponent(campaignId)}/remove-background`);
    return response.data;
  },

  // selection is 'ORIGINAL', 'PROCESSED', or null (clears it). Only
  // records which stored image this campaign should treat as its product
  // reference - see routers/marketing.py's own endpoint docstring for why
  // this does not by itself guarantee the next generated image reflects it.
  setReferenceSelection: async (campaignId, selection) => {
    const response = await httpClient.post(
      `/marketing/campaigns/${encodeURIComponent(campaignId)}/reference-selection`,
      { selection },
    );
    return response.data;
  },
};
