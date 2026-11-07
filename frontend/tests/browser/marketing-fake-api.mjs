// A stateful stand-in for the Marketing API, answered inside the browser
// (Playwright page.route) so the real Marketing Studio page can be driven
// end to end without a backend, a language model or an image service.
// It records every request so a test can check what the page really sent.
// It is NOT a substitute for marketing-images.mjs against the running app.
import { readFileSync, existsSync } from 'node:fs';

// 1x1 PNG used when no picture directory is given.
const DOT = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mN8/58BAAMBAf8XKfFlAAAAAElFTkSuQmCC', 'base64');
const SIZES = { SQUARE: [1080, 1080], PORTRAIT: [1080, 1350], STORY: [1080, 1920], LANDSCAPE: [1920, 1080], WIDE: [1200, 628] };

const COPY = {
  en: { headline: 'Taste the north of Jordan', body_copy: 'First cold press, straight from our family groves.\nOne litre of pure, golden flavour for every meal.', hashtags: ['#OliveOil', '#MadeInJordan', '#HealthyKitchen'], cta: 'Order today' },
  ar: { headline: 'تذوّق شمال الأردن', body_copy: 'عصرة أولى على البارد من بساتين العائلة.\nلتر من النكهة الذهبية النقية لكل وجبة.', hashtags: ['#زيت_زيتون', '#صنع_في_الأردن'], cta: 'اطلب اليوم' },
};
const GOOGLE = {
  en: { headline: 'Cold-pressed olive oil', body_copy: 'First press from northern Jordan. 1 litre, delivered fast.', cta: 'Shop now' },
  ar: { headline: 'زيت زيتون عصرة أولى', body_copy: 'من شمال الأردن. لتر واحد، توصيل سريع.', cta: 'تسوّق الآن' },
};

export async function installFakeApi(page, { api = 'http://localhost:8000', images, aiImages = true, campaigns = [] } = {}) {
  const picture = (format) => {
    const file = images && `${images}/${format}.png`;
    return file && existsSync(file) ? readFileSync(file) : DOT;
  };
  const state = { requests: [], campaigns: new Map(), assets: new Map(), seq: 0 };
  const asset = (format, extra = {}) => {
    state.seq += 1;
    const [width, height] = SIZES[format];
    return { asset_id: `a${state.seq}`.padEnd(12, '0'), image_format: format, width, height, mode: aiImages ? 'ai' : 'designed', attached: false, channel: null, created_at: new Date().toISOString(), ...extra };
  };
  const save = (c) => { state.campaigns.set(c.campaign_id, c); return c; };
  for (const c of campaigns) {
    save(c);
    state.assets.set(c.campaign_id, (c._assets || []).map((f, i) => asset(f, { attached: i === 0 })));
  }

  await page.route(`${api}/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    let body = null;
    try { body = request.postDataJSON(); } catch { body = null; }
    state.requests.push({ method, path, body, headers: request.headers() });
    const json = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
    const match = path.match(/^\/marketing\/campaigns\/([^/]+)(\/.*)?$/);

    if (path === '/products' && method === 'GET') {
      return json({ products: [
        { product_id: 'p1', product_name: 'Olive oil 1L', category: 'Pantry' },
        { product_id: 'p2', product_name: "Za'atar mix 250g", category: 'Spices' },
        { product_id: 'p3', product_name: 'Wild flower honey', category: 'Pantry' },
      ].filter((p) => !url.searchParams.get('search') || p.product_name.toLowerCase().includes(url.searchParams.get('search').toLowerCase())), total: 3 });
    }
    if (path.startsWith('/products/') && method === 'GET') return json({ product: { product_id: path.split('/')[2], product_name: 'Olive oil 1L', category: 'Pantry' } });
    if (path === '/marketing/options') {
      return json({ capabilities: { image_generation: { available: aiImages, external: aiImages }, background_removal: { available: false } },
        image_formats: Object.entries(SIZES).map(([key, [width, height]]) => ({ key, width, height })) });
    }
    if (path === '/marketing/image-capacity') return json({ available: false });
    if (path === '/marketing/suggestions') return json({ occasions: [{ key: 'ramadan', starts: '2027-02-08', theme: 'SEASONAL' }, { key: 'mothers_day', starts: '2027-03-21' }] });
    if (path === '/marketing/campaigns' && method === 'GET') {
      const q = (url.searchParams.get('q') || '').toLowerCase();
      const list = [...state.campaigns.values()].filter((c) => !q || c.campaign_brief.toLowerCase().includes(q)).reverse();
      return json({ campaigns: list.map((c) => ({ campaign_id: c.campaign_id, campaign_brief: c.campaign_brief, status: c.status, has_image: Boolean(c.generated_image_key), requested_at: c.requested_at, updated_at: c.updated_at })), total: list.length });
    }
    if (path === '/marketing/campaigns' && method === 'POST') {
      const language = request.headers()['x-app-language'] || 'en';
      const platforms = body.platforms || ['INSTAGRAM'];
      const id = `c${state.campaigns.size + 1}`;
      const content = Object.fromEntries(platforms.map((p) => [p, [{ variant_index: 1, ...(p === 'GOOGLE_ADS' ? GOOGLE : COPY)[language === 'ar' ? 'ar' : 'en'] }]]));
      const format = body.image_format || 'SQUARE';
      const campaign = save({
        campaign_id: id, status: 'COMPLETED', campaign_brief: body.text ? body.text.slice(0, 40) : body.url || 'Olive oil 1L',
        product_id: body.product_id || null, source_url: body.url || null, source_text: body.text || null,
        strategy_type: body.strategy_type, focus: body.focus, creative_theme: body.creative_theme || null, custom_creative_prompt: body.custom_creative_prompt || null,
        audience_summary: 'Home cooks who care about quality and origin.', creative_direction: 'Warm natural light, rustic wooden table.',
        image_prompt_default: 'A bottle of olive oil on a rustic wooden table, warm light', content, requested_at: new Date().toISOString(),
        image_generation_status: body.generate_image ? 'COMPLETED' : null, generated_image_key: body.generate_image ? 'k' : null,
      });
      state.assets.set(id, body.generate_image ? [asset(format, { attached: true })] : []);
      return json(campaign);
    }
    if (match) {
      const [, id, rest = ''] = match;
      const campaign = state.campaigns.get(id);
      if (!campaign) return json({ detail: 'Not found' }, 404);
      const list = state.assets.get(id) || [];
      if (!rest && method === 'GET') return json(campaign);
      if (!rest && method === 'PATCH') {
        if (body.title) campaign.campaign_brief = body.title;
        if (body.audience_summary !== undefined) campaign.audience_summary = body.audience_summary;
        for (const v of body.variants || []) {
          const target = campaign.content[v.platform].find((x) => x.variant_index === v.variant_index);
          Object.assign(target, Object.fromEntries(Object.entries(v).filter(([k]) => !['platform', 'variant_index'].includes(k))));
        }
        campaign.updated_at = new Date().toISOString();
        return json(campaign);
      }
      if (!rest && method === 'DELETE') { state.campaigns.delete(id); return json({ deleted: true }); }
      if (rest === '/assets' && method === 'GET') return json({ assets: list });
      if (rest === '/generate-image' && method === 'POST') {
        const made = asset(body?.image_format || 'SQUARE', { channel: body?.channel || null, prompt: body?.prompt });
        if (body?.attach !== false || !list.length) { list.forEach((a) => { a.attached = false; }); made.attached = true; campaign.generated_image_key = made.asset_id; }
        list.unshift(made);
        state.assets.set(id, list);
        return json({ campaign_id: id, image_generation_status: 'COMPLETED', image_generation_mode: made.mode, asset: made });
      }
      const assetMatch = rest.match(/^\/assets\/([^/]+)(\/image)?$/);
      if (assetMatch) {
        const item = list.find((a) => a.asset_id === assetMatch[1]);
        if (!item) return json({ detail: 'Not found' }, 404);
        if (assetMatch[2]) return route.fulfill({ status: 200, contentType: 'image/png', body: picture(item.image_format) });
        if (method === 'PATCH') {
          if (body.attach) { list.forEach((a) => { a.attached = false; }); item.attached = true; }
          if (body.clear_channel) item.channel = null; else if (body.channel) item.channel = body.channel;
          return json(item);
        }
        if (method === 'DELETE') { state.assets.set(id, list.filter((a) => a !== item)); return json({ deleted: true }); }
      }
      if (rest === '/image') return route.fulfill({ status: 200, contentType: 'image/png', body: picture('SQUARE') });
      if (rest === '/image-jobs') return json({ jobs: [], counts: { QUEUED: 0, RUNNING: 0, COMPLETED: 0, FAILED: 0, CANCELLED: 0 } });
    }
    return json({});
  });
  return state;
}

export const sampleCampaign = (id = 'c-sample', formats = ['SQUARE']) => ({
  campaign_id: id, status: 'COMPLETED', campaign_brief: 'Cold-pressed olive oil', requested_at: '2026-11-01T10:00:00Z',
  audience_summary: 'Home cooks who care about quality and origin.', creative_direction: 'Warm natural light, rustic wooden table.',
  image_prompt_default: 'A bottle of olive oil on a rustic wooden table, warm light', strategy_type: 'SALES_DRIVEN',
  content: { INSTAGRAM: [{ variant_index: 1, ...COPY.en }] }, image_generation_status: 'COMPLETED', generated_image_key: 'k', _assets: formats,
});
