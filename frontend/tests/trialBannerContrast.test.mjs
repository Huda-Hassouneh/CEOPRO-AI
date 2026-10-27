import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (file) => readFileSync(new URL(file, import.meta.url), 'utf8');
function luminance(hex) {
  const channels = hex.match(/[0-9a-f]{2}/gi).map((c) => parseInt(c, 16) / 255);
  const [r, g, b] = channels.map((v) => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
  return .2126 * r + .7152 * g + .0722 * b;
}
const onboarding = read('../src/features/onboarding/styles/Onboarding.css');
const bannerRule = onboarding.match(/\.ceopro-region-note,\s*\.ceopro-security-note,\s*\.ceopro-trial-banner,[^{]+\{([^}]+)\}/)[1];
const background = bannerRule.match(/background:\s*(#[0-9a-f]{6})/i)[1];
for (const name of ['Billing.css', 'BillingCatalogOriginal.css']) {
  test(`${name}: the small trial description meets AA on its unchanged banner background`, () => {
    const css = read('../src/features/billing/styles/' + name);
    const description = css.match(/\.ceopro-trial-banner span small\s*\{([^}]+)\}/)[1];
    const foreground = description.match(/color:\s*(#[0-9a-f]{6})/i)[1];
    const values = [luminance(foreground), luminance(background)].sort((a, b) => a - b);
    assert.ok((values[1] + .05) / (values[0] + .05) >= 4.5, 'Normal-size text must meet WCAG AA contrast');
  });
}

for (const name of ['PlansSubscription.css', 'BillingCatalogPlansOriginal.css']) {
  test(`${name}: empty-state text meets AA on the original white panel in both themes`, () => {
    const css = read('../src/features/billing/styles/' + name);
    const rules = [...css.matchAll(/\.billing-usage-unavailable\s*\{([^}]+)\}/g)];
    const rule = rules.at(-1)[1];
    assert.match(rule, /background:\s*#fff;/i);
    const foreground = rule.match(/color:\s*(#[0-9a-f]{6})/i)[1];
    assert.ok((1 + .05) / (luminance(foreground) + .05) >= 4.5);
  });
}
