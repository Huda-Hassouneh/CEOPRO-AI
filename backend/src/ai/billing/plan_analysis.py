"""Deterministic plan economics. No IO, defaults, charging or catalog mutation.

Credit allocations model provider-cost exposure, not revenue or measured spend.
Feature coverage is explicit so Credit-funded operations are not counted twice.
"""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal

from src.ai.billing.custom_plan_pricing import calculate_custom_plan_price
from src.ai.billing.pricing_math import money, round_up, price_for_margin, usage_cost

D = Decimal
ZERO = D('0')
ONE = D('1')
CADENCES = {'hourly': 60, 'every_6_hours': 360, 'every_12_hours': 720, 'daily': 1440, 'weekly': 10080}


def serial(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): serial(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serial(v) for v in value]
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return value


def analyze(plan, policy, sources, simulation=None, *, replay_legacy=False):
    """Analyze current assumptions; legacy replay is explicit and never used by HTTP analysis."""
    configuration = deepcopy(plan)
    warnings = []
    if simulation:
        for row in configuration['feature_limits']:
            if row['feature_code'] in simulation.get('limits', {}):
                row['limit_value'] = simulation['limits'][row['feature_code']]
        if simulation.get('entitlements') is not None:
            configuration['entitlements'] = simulation['entitlements']
    out = {'plan': configuration, 'publishedPlan': plan, 'currency': 'JOD', 'warnings': warnings,
           'mode': 'simulate' if simulation is not None else 'analyze', 'costs': None, 'pricing': None,
           'policyVersion': policy['version'] if policy else None,
           'observations': [x for x in sources.get('observations', []) if x['plan_key'] == plan['plan_key']]}
    if policy is None:
        warnings.append('POLICY_MISSING')
        out['status'] = 'INCOMPLETE_DATA'
        return out
    a = policy['assumptions']
    tier_specific = a.get('assumptions_schema_version') == 2
    if not tier_specific and not replay_legacy:
        out.update(status='INCOMPLETE_DATA', assumptionsSchemaVersion=1, policy=policy, assumptions=a)
        warnings.append('TIER_INTERNAL_ASSUMPTIONS_MISSING')
        return out
    internal_assumptions = a.get('internal_costs_by_plan', {}).get(plan['plan_key']) if tier_specific else None
    if tier_specific and not internal_assumptions:
        out.update(status='INCOMPLETE_DATA', assumptionsSchemaVersion=2, policy=policy, assumptions=a)
        warnings.append('TIER_INTERNAL_ASSUMPTIONS_MISSING')
        return out
    if tier_specific:
        out.update(assumptionsSchemaVersion=2, internalAssumptions=internal_assumptions)
        if any(internal_assumptions[s]['status'] == 'provisional' for s in ('expected', 'stress')):
            warnings.append('INTERNAL_ASSUMPTIONS_PROVISIONAL')
    fx = D(a['usd_to_jod'])
    as_of = datetime.fromisoformat(sources['as_of'])
    bindings = sources.get('bindings', [])
    limits = {r['feature_code']: r for r in configuration['feature_limits']}
    selected = {code for code, r in limits.items() if r['limit_value'] is None or r['limit_value'] > 0} | set(configuration['entitlements'])
    treatments = a['feature_treatments']
    recurring = {'expected': ZERO, 'stress': ZERO}
    allowance = {'expected': ZERO, 'stress': ZERO}
    breakdown = []
    evidence = []
    incomplete = False

    def warn(code, feature):
        nonlocal incomplete
        incomplete = True
        warnings.append(code + ':' + feature)

    credit_value = sources.get('credit_policy', {}).get('credit_usd_value')
    for kind in ('ai', 'data'):
        code = kind + '_credits'
        row = limits.get(code)
        if row is None or row['limit_value'] is None or credit_value is None:
            warn('CREDIT_BUDGET_UNAVAILABLE', code)
            continue
        base = D(row['limit_value']) * D(credit_value) * fx
        costs = {s: base * D(a[s + '_utilization']) for s in allowance}
        for scenario in allowance:
            allowance[scenario] += costs[scenario]
        breakdown.append({'feature': code, 'category': kind, 'source': 'billing_cost_policy.credit_usd_value',
                          'classification': 'configured_credit_exposure', **costs})

    for code in sorted(selected - {'ai_credits', 'data_credits'}):
        canonical = sources.get('feature_economics', {}).get(code)
        coverage = treatments.get(code) or (canonical['treatment'] if canonical else None)
        # Provider calls in these capabilities already settle against Credit
        # pools. An additional copy of that spend would inflate plan economics.
        if canonical and canonical['treatment'] in ('ai_credits', 'data_credits', 'ai_and_data_credits') and coverage == 'additional_external':
            warn('CREDIT_COVERAGE_CONFLICT', code)
            continue
        if coverage is None:
            warn('COST_COVERAGE_MISSING', code)
            continue
        if coverage in ('ai_credits', 'data_credits', 'ai_and_data_credits', 'internal_allocation'):
            breakdown.append({'feature': code, 'category': coverage, 'classification': 'configured_coverage',
                              'coverageSource': 'owner_policy' if code in treatments else canonical,
                              'expected': ZERO, 'stress': ZERO})
            continue
        rates = [b for b in bindings if b['feature_code'] == code]
        if not rates:
            warn('RATE_MISSING', code)
            continue
        row = limits.get(code)
        quantity = row['limit_value'] if row else 1
        if quantity is None:
            quantity = a['unlimited_monthly_usage'].get(code)
        if quantity is None:
            warn('UNBOUNDED_USAGE', code)
            continue
        feature = {'feature_id': code, 'feature_code': code, 'limit_value': D(quantity), 'estimated_usage': D(quantity)}
        features = [feature]
        if code == 'competitor_management':
            cadence = (simulation or {}).get('refresh_frequency') or a.get('refresh_frequency')
            capacity = limits.get('tracked_competitors', {}).get('limit_value')
            if capacity is None:
                capacity = a['unlimited_monthly_usage'].get('tracked_competitors')
            if cadence not in CADENCES or not capacity:
                warn('MONITORING_ASSUMPTION_MISSING', code)
                continue
            feature['configuration'] = {'monitoring_frequency_minutes': CADENCES[cadence]}
            features.append({'feature_id': 'tracked_competitors', 'feature_code': 'tracked_competitors',
                             'limit_value': D(capacity), 'estimated_usage': D(capacity)})
        vendor, infra = [], []
        valid = True
        for b in rates:
            evidence.append(b)
            verified = b.get('verified_at')
            if not b.get('rate_id') or b.get('unit_cost_usd') is None:
                warn('RATE_MISSING', code); valid = False; continue
            if not b.get('cost_is_final') or not b.get('rate_source') or not verified or str(verified) > as_of.date().isoformat():
                warn('RATE_UNVERIFIED', code); valid = False; continue
            age = (as_of.date() - datetime.fromisoformat(str(verified)).date()).days
            if age > a['max_rate_age_days']:
                warn('RATE_STALE', code); valid = False; continue
            if b.get('operational_multiplier') is None or b.get('variability_reserve') is None:
                warn('COST_MULTIPLIER_MISSING', code); valid = False; continue
            rate = {'id': b['binding_id'], 'feature_id': code, 'feature': {'code': code},
                    'unit_cost': D(b['unit_cost_usd']), 'currency': 'USD', 'vendor': b['provider'],
                    'service': b['operation'], 'billing_unit': b['unit'], 'verification_status': 'confirmed',
                    'source': b['rate_source'], 'operational_multiplier': b['operational_multiplier'],
                    'variability_reserve': b['variability_reserve'], 'metadata': {'usageAssumption': b['usage_assumption']}}
            if b['cost_category'] == 'vendor':
                if b['usage_basis'] == 'limit_value':
                    rate['unit_cost'] *= D(b['units_per_feature_unit'])
                vendor.append(rate)
            else:
                rate.update(cost_driver=b['operation'], usage_basis=b['usage_basis'], billing_units_per_feature_unit=b['units_per_feature_unit'])
                infra.append(rate)
        if not valid:
            continue
        result = calculate_custom_plan_price({'features': features, 'vendor_rates': vendor, 'infrastructure_rates': infra,
            'vendor_cost_required_feature_ids': [], 'quote_currency': 'JOD', 'fx_rate': fx,
            'fx_source_currency': 'USD', 'fx_target_currency': 'JOD', 'monthly_infrastructure_cost': ZERO,
            'active_paying_tenants': 1, 'estimated_other_cost': ZERO, 'target_gross_margin': ZERO,
            'fixed_platform_fee': ZERO, 'rounding_increment': ZERO})
        # Cost engine receives full configured capacity; utilization scales its
        # resulting exposure once, including competitor checks and fixed drivers.
        # Keep micro-cost precision through utilization and aggregation. The
        # legacy calculator's public totals intentionally round to cents.
        base = sum((usage_cost(D(r.get('estimatedUsage', r.get('normalizedBillableQuantity'))),
                               D(r['normalizedUnitCost']), D(r['operationalMultiplier']), D(r['variabilityReserve']))
                    for r in result['vendorBreakdown'] + result['infrastructureBreakdown']), ZERO)
        bucket = allowance if row and row['reset_cycle'] == 'billing_period' and row['aggregation_type'] == 'sum' else recurring
        costs = {s: base * D(a[s + '_utilization']) for s in bucket}
        for scenario in bucket:
            bucket[scenario] += costs[scenario]
        breakdown.append({'feature': code, 'category': 'additional_external', 'classification': 'configured_usage_verified_rate',
                          'source': 'billing_custom_cost_bindings', 'calculation': result, **costs})
    if tier_specific:
        internal = {s: D(internal_assumptions[s]['monthly_jod']) for s in recurring}
    else:
        legacy_internal = D(a['infrastructure_jod']) + D(a['support_jod']) + D(a['operations_jod'])
        internal = {s: legacy_internal for s in recurring}
    cost = {s: recurring[s] + allowance[s] + internal[s] for s in recurring}
    out.update(costs={'expected': money(cost['expected']), 'stress': money(cost['stress']),
                     'knownSubtotalOnly': incomplete, 'breakdown': breakdown,
                     'recurringExternal': recurring, 'periodAllowances': allowance},
               rateEvidence=evidence, policy=policy, creditPolicy=sources.get('credit_policy'),
               fx={'usdToJod': str(fx), 'source': a['fx_source'], 'version': a['fx_version']},
               assumptions=a)
    if tier_specific:
        out['costs'].update(internalByScenario=internal,
            externalByScenario={s: recurring[s] + allowance[s] for s in recurring})
    else:
        out['costs']['internal'] = legacy_internal
    if incomplete:
        out['status'] = 'INCOMPLETE_DATA'
        return out
    percent, fixed = D(a['processing_ratio']), D(a['processing_fixed_jod'])
    buffer = ONE + D(a['risk_buffer'])

    def prices(expected, stress):
        break_even = price_for_margin(expected, ZERO, percent, fixed)
        safe = price_for_margin(stress * buffer, D(a['minimum_margin']), percent, fixed)
        target = price_for_margin(expected * buffer, D(a['target_margin']), percent, fixed)
        return {'breakEven': money(break_even), 'safeMinimum': round_up(safe, D(a['rounding_jod'])),
                'target': round_up(target, D(a['rounding_jod'])), 'recommended': round_up(max(safe, target), D(a['rounding_jod']))}

    pricing = prices(cost['expected'], cost['stress'])
    monthly = next((p for p in plan['prices'] if p['interval_months'] == 1), None)
    published = D(monthly['amount']) if monthly else D(plan['monthly_price']) if plan.get('monthly_price') is not None else None
    currency = monthly['currency'] if monthly else plan['currency']
    current = published * (fx if currency == 'USD' else ONE) if published is not None and currency in ('USD', 'JOD') else None

    def margins(revenue, expected, stress):
        if revenue is None or revenue <= 0:
            return {'contribution': None, 'expectedMargin': None, 'stressMargin': None}
        contribution = revenue * (ONE - percent) - fixed - expected
        return {'contribution': money(contribution), 'expectedMargin': contribution / revenue,
                'stressMargin': (revenue * (ONE - percent) - fixed - stress) / revenue}

    pricing.update(currentJod=current, publishedAmount=published, publishedCurrency=currency,
                   difference=money(pricing['recommended'] - current) if current is not None else None,
                   **margins(current, cost['expected'], cost['stress']))
    periods = []
    for p in plan['prices']:
        months = int(p['interval_months'])
        revenue = D(p['amount']) * (fx if p['currency'] == 'USD' else ONE) if p['currency'] in ('USD', 'JOD') else None
        # Actual KEEL sum allowances reset per assigned billing period; they
        # are not silently multiplied by a multi-month Stripe interval.
        expected = (recurring['expected'] + internal['expected']) * months + allowance['expected']
        stress = (recurring['stress'] + internal['stress']) * months + allowance['stress']
        periods.append({'period': p['period_code'], 'months': months, 'revenueJod': revenue,
                        'expectedCost': money(expected), 'stressCost': money(stress), **margins(revenue, expected, stress)})
    cycles = D(a['annual_allowance_cycles'])
    annual_expected = (recurring['expected'] + internal['expected']) * 12 + allowance['expected'] * cycles
    annual_stress = (recurring['stress'] + internal['stress']) * 12 + allowance['stress'] * cycles
    annual = prices(annual_expected, annual_stress)
    annual['discountedCandidate'] = round_up(pricing['recommended'] * 12 * (ONE - D(a['annual_discount'])), D(a['rounding_jod']))
    annual.update(expectedCost=money(annual_expected), stressCost=money(annual_stress),
                  allowanceCycles=a['annual_allowance_cycles'], **margins(annual['discountedCandidate'], annual_expected, annual_stress))
    if annual['discountedCandidate'] < annual['safeMinimum']:
        warnings.append('ANNUAL_DISCOUNT_UNSAFE')
    if pricing['stressMargin'] is not None and pricing['stressMargin'] < D(a['minimum_margin']):
        warnings.append('CURRENT_PRICE_UNSAFE')
    if current is None:
        warnings.append('PUBLISHED_PRICE_UNAVAILABLE')
    status = 'PROVISIONAL' if 'INTERNAL_ASSUMPTIONS_PROVISIONAL' in warnings else 'WARNING' if warnings else 'SAFE'
    out.update(pricing=pricing, annual=annual, periods=periods, status=status)
    return out


def ladder(analyses, policy, *, plan_order=None):
    if plan_order is None:
        ordered = sorted(analyses, key=lambda x: x['plan']['tier_level'])
    else:
        by_key = {a['plan']['plan_key']: a for a in analyses}
        ordered = [by_key[key] for key in plan_order if key in by_key]
    warnings = []
    for low, high in zip(ordered, ordered[1:]):
        if not low.get('pricing') or not high.get('pricing'):
            continue
        lp, hp = low['pricing']['currentJod'], high['pricing']['currentJod']
        lc, hc = low['costs']['stress'], high['costs']['stress']
        pair = {'lower': low['plan']['plan_key'], 'higher': high['plan']['plan_key']}
        if lp is None or hp is None or lp <= 0:
            continue
        if hp <= lp:
            warnings.append({**pair, 'code': 'NON_INCREASING_PRICE'})
        threshold = policy['assumptions'].get('ladder_min_price_gap') if policy else None
        if threshold is not None and hc > lc and (hp - lp) / lp < D(threshold):
            warnings.append({**pair, 'code': 'WEAK_PRICE_GAP_FOR_COST_INCREASE'})
        if lc > 0 and hc / lc > hp / lp:
            warnings.append({**pair, 'code': 'COST_GROWS_FASTER_THAN_PRICE'})
        low_limits = {r['feature_code']: r['limit_value'] for r in low['plan']['feature_limits']}
        high_limits = {r['feature_code']: r['limit_value'] for r in high['plan']['feature_limits']}
        dominates = all(code in low_limits and (low_limits[code] is None or
                        (value is not None and low_limits[code] >= value)) for code, value in high_limits.items())
        if lp <= hp and dominates and set(low['plan']['entitlements']) >= set(high['plan']['entitlements']):
            warnings.append({**pair, 'code': 'LOWER_TIER_DOMINATES_ALLOWANCES'})
    return warnings
