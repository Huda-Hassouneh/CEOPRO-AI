"""Owner analysis use cases. Catalog/payment authorities are read-only inputs."""
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from psycopg2.extras import Json

from src.ai.billing import plan_analysis, economic_catalog, standard_plan_catalog


class Assumptions(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    target_margin: Decimal = Field(ge=0, lt=1, allow_inf_nan=False)
    minimum_margin: Decimal = Field(ge=0, lt=1, allow_inf_nan=False)
    risk_buffer: Decimal = Field(ge=0, allow_inf_nan=False)
    expected_utilization: Decimal = Field(ge=0, le=1, allow_inf_nan=False)
    stress_utilization: Decimal = Field(ge=0, le=1, allow_inf_nan=False)
    infrastructure_jod: Decimal = Field(ge=0, allow_inf_nan=False)
    support_jod: Decimal = Field(ge=0, allow_inf_nan=False)
    operations_jod: Decimal = Field(ge=0, allow_inf_nan=False)
    processing_ratio: Decimal = Field(ge=0, lt=1, allow_inf_nan=False)
    processing_fixed_jod: Decimal = Field(ge=0, allow_inf_nan=False)
    annual_discount: Decimal = Field(ge=0, lt=1, allow_inf_nan=False)
    annual_allowance_cycles: StrictInt = Field(ge=1, le=12)
    rounding_jod: Decimal = Field(gt=0, allow_inf_nan=False)
    usd_to_jod: Decimal = Field(gt=0, allow_inf_nan=False)
    fx_source: str = Field(min_length=1, max_length=2000)
    fx_version: str = Field(min_length=1, max_length=200)
    max_rate_age_days: StrictInt = Field(ge=1, le=36500)
    cost_binding_policy_id: UUID | None = None
    feature_treatments: dict[str, Literal['ai_credits', 'data_credits', 'ai_and_data_credits', 'internal_allocation', 'additional_external']]
    unlimited_monthly_usage: dict[str, StrictInt] = Field(default_factory=dict)
    refresh_frequency: Literal['hourly', 'every_6_hours', 'every_12_hours', 'daily', 'weekly'] | None = None
    ladder_min_price_gap: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode='after')
    def consistent(self):
        if self.minimum_margin > self.target_margin or self.stress_utilization < self.expected_utilization:
            raise ValueError('Minimum margin must not exceed target; stress utilization must not be below expected')
        if self.target_margin + self.processing_ratio >= 1:
            raise ValueError('Target margin plus payment processing must be below one')
        if any(x < 0 for x in self.unlimited_monthly_usage.values()):
            raise ValueError('Unlimited capacity estimates must be nonnegative')
        if self.rounding_jod % Decimal('.01') != 0:
            raise ValueError('Rounding increment must be a positive whole number of cents')
        return self


class PolicyCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    effective_from: datetime
    reason: str = Field(min_length=1, max_length=2000)
    assumptions: Assumptions

    @model_validator(mode='after')
    def aware(self):
        if self.effective_from.tzinfo is None:
            raise ValueError('Effective date requires a timezone')
        return self


class Simulation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    limits: dict[str, StrictInt | None] = Field(default_factory=dict)
    entitlements: list[str] | None = None
    refresh_frequency: Literal['hourly', 'every_6_hours', 'every_12_hours', 'daily', 'weekly'] | None = None

    @model_validator(mode='after')
    def nonnegative(self):
        if any(x is not None and x < 0 for x in self.limits.values()):
            raise ValueError('Quantities must be nonnegative; null preserves unbounded capacity')
        return self


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    plan_key: str = Field(min_length=1, max_length=50)
    policy_id: UUID | None = None
    simulation: Simulation | None = None


def command(conn, action, payload=None):
    with conn.cursor() as cur:
        cur.execute('SELECT public.billing_plan_studio(%s,%s::jsonb)::text', (action, Json(plan_analysis.serial(payload or {}))))
        return json.loads(cur.fetchone()[0], parse_float=Decimal)


def bootstrap(conn):
    sources = command(conn, 'inputs')
    sources['feature_economics'] = economic_catalog.coverage()
    sources['provider_readiness'] = economic_catalog.readiness(sources['provider_rates'], as_of=sources['as_of'][:10],
        max_rate_age_days=(sources.get('selected_policy') or {}).get('assumptions', {}).get('max_rate_age_days'))
    # Private evidence is owner-only; no customer endpoint imports this use case.
    return plan_analysis.serial(sources)


def create_policy(conn, body):
    data = body.model_dump(mode='json')
    sources = command(conn, 'inputs')
    codes = {r['feature_code'] for r in sources['features']} | set(sources['entitlement_catalog'])
    if set(body.assumptions.feature_treatments) - codes or set(body.assumptions.unlimited_monthly_usage) - codes:
        raise ValueError('Policy refers to an unsupported feature')
    return command(conn, 'create_policy', data)


def run_analysis(conn, body):
    sources = command(conn, 'inputs', {'policy_id': str(body.policy_id)} if body.policy_id else {})
    sources['feature_economics'] = economic_catalog.coverage()
    plan = next((p for p in sources['plans'] if p['plan_key'] == body.plan_key), None)
    if plan is None:
        raise ValueError('Select a current Standard Plan')
    policy = sources['selected_policy']
    if policy:
        # Validate stored values as well as HTTP writes; unsafe legacy/direct SQL
        # inputs cannot silently become economic assumptions.
        policy['assumptions'] = Assumptions.model_validate(policy['assumptions']).model_dump(mode='json')
    simulation = body.simulation.model_dump() if body.simulation else None
    if simulation:
        limits = {r['feature_code'] for r in plan['feature_limits']}
        modules = set(sources['entitlement_catalog'])
        if set(simulation['limits']) - limits or set(simulation.get('entitlements') or []) - modules:
            raise ValueError('Simulation must use supported plan quantities and entitlements')
    result = plan_analysis.analyze(plan, policy, sources, simulation)
    # self_serve also includes compatibility identities and owner drafts.
    # Compare current tiers using installed catalog membership/order, while
    # retaining every plan in the owner inputs for individual analysis.
    catalog = standard_plan_catalog.installed_catalog(conn)
    plan_order = [p['plan_key'] for p in sorted(catalog['plans'], key=lambda p: p['tier_level'])]
    by_key = {p['plan_key']: p for p in sources['plans']}
    neighbors = [plan_analysis.analyze(by_key[key], policy, sources) for key in plan_order if key in by_key]
    result['neighbors'] = [{'planKey': p['plan']['plan_key'], 'pricing': p['pricing'], 'costs': p['costs'], 'status': p['status']} for p in neighbors]
    result['ladderWarnings'] = plan_analysis.ladder(neighbors, policy, plan_order=plan_order)
    result['asOf'] = sources['as_of']
    result['evidence'] = {'providerSchedules': sources['provider_rates'], 'observations': sources['observations'],
                          'comparisonCatalog': {'version': catalog['catalog_version'], 'planKeys': plan_order},
                          'creditPolicy': sources['credit_policy'], 'window': sources['observation_window'],
                          'featureEconomics': sources['feature_economics'],
                          'providerReadiness': economic_catalog.readiness(sources['provider_rates'], as_of=sources['as_of'][:10],
                              max_rate_age_days=policy['assumptions']['max_rate_age_days'] if policy else None)}
    for row in result['evidence']['providerSchedules']:
        verified = row.get('verified_at')
        status = 'VERIFIED'
        if row.get('unit_cost_usd') is None:
            status = 'MISSING'
        elif not row.get('cost_is_final') or not row.get('source') or not verified or verified > sources['as_of'][:10]:
            status = 'UNVERIFIED'
        elif policy and (datetime.fromisoformat(sources['as_of']).date() - datetime.fromisoformat(verified).date()).days > policy['assumptions']['max_rate_age_days']:
            status = 'STALE'
        row['analysisStatus'] = status
    frozen = plan_analysis.serial(result)
    canonical = json.dumps(frozen, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    saved = command(conn, 'save_analysis', {'plan_key': body.plan_key, 'mode': result['mode'],
        'policy_id': policy['policy_id'] if policy else None, 'snapshot': frozen, 'source_hash': digest})
    return {**frozen, 'analysisId': saved['analysis_id'], 'sourceHash': digest}
