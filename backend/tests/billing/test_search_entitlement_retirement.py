"""Compatibility and real Redis capacity boundaries; no external HTTP calls."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

import pytest

from src.ai.billing import admin, credits, custom_offers, service
from src.ai.billing.standard_plan_catalog import load_catalog
from src.ai.core import feature_contracts as features, usage
from src.market_scraper import provider_billing, search_safety
from .test_custom_quote_lifecycle_db import quote_actors, _conn  # noqa: F401


def test_new_catalog_retires_only_search_and_preserves_economic_values():
    c = load_catalog()
    assert c['catalog_version'] == 'standard-plans-lean-search-v1'
    assert features.WEB_SEARCHES in features.QUANTITATIVE_FEATURES
    assert set(features.COMMERCIAL_QUANTITATIVE_FEATURES) == set(features.QUANTITATIVE_FEATURES) - {'web_searches'}
    for p in c['plans']:
        assert 'web_searches' not in p['features']
        assert {a['feature_key'] for a in p['allowances']} == set(features.COMMERCIAL_QUANTITATIVE_FEATURES)
    # Historical quotes can still close their original contract without a rewrite.
    assert admin.closed_quote_limits({'web_searches': 17})['web_searches'] == 17


@pytest.mark.parametrize('before,after', [({'limit': 100}, None), (None, {'limit': 500}),
                                       ({'limit': 100}, {'limit': 1})])
def test_transition_ignores_only_retired_search(before, after):
    a = {'features': {'ai_credits': {'limit': 10}}, 'entitlements': ['product_management']}
    b = deepcopy(a)
    if before is not None:
        a['features']['web_searches'] = before
    if after is not None:
        b['features']['web_searches'] = after
    assert service._classify_rights_change(a, b) == ('unchanged', ())
    b['features']['ai_credits']['limit'] = 11
    assert service._classify_rights_change(a, b) == ('gain', ())
    b['features']['monthly_reports'] = {'limit': 2}
    assert service._classify_rights_change(a, b) == ('unclassified', ('monthly_reports',))


def test_custom_new_choices_reject_search_but_legacy_revision_is_readable(monkeypatch):
    monkeypatch.setattr(custom_offers, 'feature_catalog', lambda conn: [{'featureCode': 'ai_credits'}])
    with pytest.raises(custom_offers.CustomOfferError, match='no longer sold'):
        custom_offers.validate_configuration(None, limits={'web_searches': 5}, refresh_frequency=None)
    result = custom_offers.validate_configuration(None, limits={'web_searches': 5, 'ai_credits': 2},
                                                legacy_limits={'web_searches': 5}, refresh_frequency=None)
    assert result['configuration']['limits']['web_searches'] == 5
    with pytest.raises(custom_offers.CustomOfferError):
        custom_offers.validate_configuration(None, limits={'web_searches': 6},
                                             legacy_limits={'web_searches': 5}, refresh_frequency=None)


def test_legacy_custom_pricing_revalidation_preserves_old_selection(monkeypatch):
    from src.ai.billing import custom_plan_pricing_service as pricing
    monkeypatch.setattr(custom_offers, 'feature_catalog', lambda conn: [{'featureCode': 'ai_credits'}])
    monkeypatch.setattr(pricing, 'active_policy', lambda *a: None)
    limits = {'web_searches': 5, 'ai_credits': 2}
    result = pricing.calculate_preview(None, limits=limits, legacy_limits=limits, refresh_frequency=None)
    assert result['reasons'] == ['active_pricing_policy_missing']
    assert limits == {'web_searches': 5, 'ai_credits': 2}
    with pytest.raises(custom_offers.CustomOfferError):
        pricing.calculate_preview(None, limits=limits, refresh_frequency=None)


@pytest.fixture
def capacity(monkeypatch):
    import redis
    host, port = os.getenv('AI_TEST_REDIS_HOST'), os.getenv('AI_TEST_REDIS_PORT')
    if not host or not port:
        pytest.skip('Requires disposable test Redis from the isolated runner')
    client = redis.Redis(host=host, port=int(port), decode_responses=True)
    client.ping()
    monkeypatch.setattr(search_safety, 'get_shared_redis_client', lambda **kw: client)
    monkeypatch.setattr(credits, 'ensure_access', lambda *a, **kw: None)
    # Unique provider/tenant identities keep tests isolated without flushdb.
    return client, 'fixture_' + uuid4().hex, str(uuid4())


def test_free_call_at_zero_credits_never_enters_monetary_accounting(capacity, monkeypatch):
    client, provider, tid = capacity
    monkeypatch.setattr(provider_billing, '_free_hosts', lambda: {'fixture.test': provider})
    monkeypatch.setattr(credits, 'provider_call', lambda *a, **kw: pytest.fail('Free call must not charge'))
    with credits.metering(tid, 'search_fixture'):
        assert provider_billing.metered_request('https://fixture.test/search', lambda: {'ok': True}) == {'ok': True}
    metrics = list(client.scan_iter('keel:search:safety:requests:' + search_safety.fingerprint(provider) + ':*'))
    assert len(metrics) == 1
    assert client.hget(metrics[0], 'request:free:succeeded') == '1'


def test_paid_call_still_reserves_sends_and_settles(capacity, monkeypatch):
    _, provider, tid = capacity
    seen = []
    class Call:
        def sent(self): seen.append('sent')
        def measured(self, units): seen.append(units)
    @contextmanager
    def charge(*args):
        seen.append(args)
        yield Call()
        seen.append('settled')
    monkeypatch.setattr(provider_billing, 'classify', lambda url: (provider, 'search', 'request'))
    monkeypatch.setattr(credits, 'provider_call', charge)
    with credits.metering(tid, 'search_fixture'):
        assert provider_billing.metered_request('https://paid.test', lambda: [1]) == [1]
    assert seen == [(credits.DATA, provider, 'search', {'request': 1}), 'sent', {'request': 1}, 'settled']


def test_paid_budget_failure_does_not_send(capacity, monkeypatch):
    _, provider, tid = capacity
    monkeypatch.setattr(provider_billing, 'classify', lambda url: (provider, 'search', 'request'))
    @contextmanager
    def blocked(*args):
        raise credits.BudgetError('BUDGET_EXHAUSTED', credits.DATA)
        yield
    monkeypatch.setattr(credits, 'provider_call', blocked)
    with credits.metering(tid, 'search_fixture'), pytest.raises(credits.BudgetError):
        provider_billing.metered_request('https://paid.test', lambda: pytest.fail('Must not send'))


def test_no_context_or_subscription_cannot_use_free_provider(capacity, monkeypatch):
    with pytest.raises(search_safety.SearchCapacityError):
        with search_safety.admission('free', 'search', free=True):
            pytest.fail('Must not send')
    def inactive(*a):
        raise credits.BudgetError('SUBSCRIPTION_INACTIVE', credits.DATA)
    monkeypatch.setattr(credits, 'ensure_access', inactive)
    with credits.metering(str(uuid4()), 'search_fixture'), pytest.raises(credits.BudgetError):
        with search_safety.admission('free', 'search', free=True):
            pytest.fail('Must not send')


@pytest.mark.parametrize('limit', ['TENANT_PER_MINUTE', 'TENANT_PER_DAY', 'PROVIDER_PER_MINUTE', 'PROVIDER_PER_DAY'])
def test_atomic_capacity_limits(capacity, monkeypatch, limit):
    _, provider, tid = capacity
    monkeypatch.setenv('SEARCH_' + limit, '1')
    with credits.metering(tid, 'fixture'):
        with search_safety.admission(provider, 'search', free=True): pass
        with pytest.raises(search_safety.SearchCapacityError):
            with search_safety.admission(provider, 'search', free=True): pass


@pytest.mark.parametrize('limit', ['TENANT_CONCURRENCY', 'PROVIDER_CONCURRENCY'])
def test_concurrency_and_duplicate_release(capacity, monkeypatch, limit):
    _, provider, tid = capacity
    monkeypatch.setenv('SEARCH_' + limit, '1')
    with credits.metering(tid, 'fixture'):
        with search_safety.admission(provider, 'search', free=True, request_key='a'):
            with pytest.raises(search_safety.SearchCapacityError):
                with search_safety.admission(provider, 'search', free=True, request_key='b'): pass
        with search_safety.admission(provider, 'search', free=True, request_key='a'): pass


def test_inflight_duplicate_is_refused_other_tenant_is_independent(capacity):
    _, provider, tid = capacity
    with credits.metering(tid, 'fixture'):
        with search_safety.admission(provider, 'search', free=True, request_key='same'):
            with pytest.raises(search_safety.SearchCapacityError):
                with search_safety.admission(provider, 'search', free=True, request_key='same'): pass
            with credits.metering(str(uuid4()), 'fixture'):
                with search_safety.admission(provider, 'search', free=True, request_key='same'): pass


def test_concurrent_requests_cannot_overshoot_budget(capacity, monkeypatch):
    _, provider, tid = capacity
    monkeypatch.setenv('SEARCH_TENANT_PER_MINUTE', '1')
    def request(i):
        try:
            with credits.metering(tid, 'fixture'):
                with search_safety.admission(provider, 'search', free=True): return True
        except search_safety.SearchCapacityError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(request, range(8))) == 1


def test_redis_outage_is_fail_closed(monkeypatch):
    def down(**kw): raise ConnectionError('fixture')
    monkeypatch.setattr(search_safety, 'get_shared_redis_client', down)
    monkeypatch.setattr(credits, 'ensure_access', lambda *a: None)
    with credits.metering(str(uuid4()), 'fixture'), pytest.raises(search_safety.SearchCapacityError, match='storage unavailable'):
        with search_safety.admission('free', 'search', free=True): pytest.fail('Must not send')


def test_research_fairness_storage_failure_does_not_allow_search(monkeypatch):
    from src.ai.core import redis_client
    from src.ai.research import research
    def down(**kw): raise ConnectionError('fixture')
    monkeypatch.setattr(redis_client, 'get_redis_client', down)
    assert research._tenant_budget_ok(str(uuid4())) is False


@pytest.mark.parametrize('url', ['https://overpass-api.de/api/interpreter', 'https://api.tavily.com/search'])
def test_limiter_outage_never_sends_free_or_paid_requests(monkeypatch, url):
    def down(**kw): raise ConnectionError('fixture')
    monkeypatch.setattr(search_safety, 'get_shared_redis_client', down)
    monkeypatch.setattr(credits, 'ensure_access', lambda *a: None)
    with credits.metering(str(uuid4()), 'fixture'), pytest.raises(search_safety.SearchCapacityError):
        provider_billing.metered_request(url, lambda: pytest.fail('No request may leave during limiter outage'))


def test_bad_limiter_storage_is_fail_closed_without_disabling_other_redis_work(capacity):
    client, provider, tid = capacity
    key = 'keel:search:safety:tenant:' + search_safety.fingerprint(tid) + ':minute'
    client.set(key, 'invalid-counter', ex=60)
    with credits.metering(tid, 'fixture'), pytest.raises(search_safety.SearchCapacityError):
        with search_safety.admission(provider, 'search', free=True): pytest.fail('Must not send')
    other = 'fixture:unrelated:' + uuid4().hex
    assert client.ping()
    client.set(other, 'available', ex=60)
    assert client.get(other) == 'available'


def test_limiter_outage_does_not_disable_authenticated_billing_reads(
        client, tenant, billing_connections, monkeypatch):
    from src.ai.core.security import TenantContext
    from src.ai.routers import billing
    def down(**kw): raise ConnectionError('fixture')
    monkeypatch.setattr(search_safety, 'get_shared_redis_client', down)
    client.app.dependency_overrides[billing.get_tenant_context] = lambda: TenantContext(*tenant)
    try:
        assert client.get('/billing/plans').status_code == 200
        response = client.get('/billing/subscription')
        assert response.status_code == 200, response.text
        assert response.json()['hasSubscription'] is False
    finally:
        client.app.dependency_overrides.clear()


def test_search_limiter_outage_does_not_disable_marketing_copy_or_image_generation(monkeypatch):
    from src.ai.marketing import content_generator, image_generation
    from src.ai.tests.test_marketing_content_generator import scripted_campaign_completion
    from src.ai.tests.test_marketing_image_generation import PNG, _response
    def down(**kw): raise ConnectionError('fixture')
    monkeypatch.setattr(search_safety, 'get_shared_redis_client', down)
    # Provider transport and monetary accounting are explicit unit doubles;
    # native AI settlement during the same outage has separate DB coverage.
    monkeypatch.setattr(credits, '_bypassed_for_tests', lambda: True)
    monkeypatch.setattr(content_generator.llm_client, 'chat_completion',
                        lambda *a, **kw: scripted_campaign_completion(*a, **kw)[0])
    monkeypatch.setattr(image_generation.httpx, 'post', lambda *a, **kw: _response(content=PNG))
    monkeypatch.setattr(image_generation, '_cooling_down', lambda *a: False)
    monkeypatch.setenv('HUGGINGFACE_API_TOKEN', 'fixture-only')
    with credits.metering(str(uuid4()), 'fixture'):
        with pytest.raises(search_safety.SearchCapacityError):
            provider_billing.metered_request('https://overpass-api.de/api/interpreter',
                                            lambda: pytest.fail('Search must not send'))
        copy = content_generator.generate_campaign_content('A round white dial and black strap.')
        image = image_generation.generate_campaign_image('A watch on a desk', provider='huggingface')
    assert copy.variants_by_platform['INSTAGRAM']
    assert image.content == PNG and image.provider == 'huggingface'


def test_crashed_worker_lease_expires_and_failure_releases(capacity):
    client, provider, tid = capacity
    tenant_key = 'keel:search:safety:tenant:' + search_safety.fingerprint(tid) + ':inflight'
    client.zadd(tenant_key, {'crashed': 1})
    with credits.metering(tid, 'fixture'):
        with pytest.raises(ValueError):
            with search_safety.admission(provider, 'search', free=True, request_key='retry'):
                raise ValueError('fixture failure')
        with search_safety.admission(provider, 'search', free=True, request_key='retry'): pass
    assert client.zcard(tenant_key) == 0


def test_capacity_window_ttl_is_not_extended_by_traffic(capacity):
    client, provider, tid = capacity
    with credits.metering(tid, 'fixture'):
        with search_safety.admission(provider, 'search', free=True): pass
        key = 'keel:search:safety:tenant:' + search_safety.fingerprint(tid) + ':minute'
        client.expire(key, 15)
        with search_safety.admission(provider, 'search', free=True): pass
        assert 0 < client.ttl(key) <= 15


def test_discovery_cache_hit_does_not_repeat_outbound_work(capacity, monkeypatch):
    from src.market_scraper.market_discovery import http
    client, provider, tid = capacity
    monkeypatch.setattr(http, '_cache', lambda: client)
    monkeypatch.setattr(provider_billing, '_free_hosts', lambda: {'fixture.test': provider})
    calls = []
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'fixture': True}
    class HTTP:
        def __init__(self, **kw): assert kw['timeout'] <= 30
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def request(self, *a, **kw): calls.append(1); return Response()
    monkeypatch.setattr(http.httpx, 'Client', HTTP)
    url = 'https://fixture.test/' + uuid4().hex
    with credits.metering(tid, 'fixture'):
        assert http.request_json('GET', url, timeout=100) == {'fixture': True}
        assert http.request_json('GET', url, timeout=100) == {'fixture': True}
    assert calls == [1]


def test_configured_fallbacks_are_unique_and_bounded(monkeypatch):
    from src.market_scraper import web_search
    from src.market_scraper.market_discovery.providers import osm
    monkeypatch.setenv('WEB_SEARCH_PROVIDERS', 'tavily,tavily,searxng,tavily')
    monkeypatch.setattr(web_search, 'secret', lambda setting: 'fixture')
    assert web_search.configured_providers() == ['tavily', 'searxng']
    monkeypatch.setenv('OVERPASS_API_URLS', 'https://a.test,https://a.test,https://b.test,https://c.test,https://d.test')
    assert osm.overpass_urls() == ['https://a.test', 'https://b.test', 'https://c.test']


def test_free_access_admission_does_not_read_credit_balance(monkeypatch):
    monkeypatch.setattr(credits, '_bypassed_for_tests', lambda: False)
    monkeypatch.setattr(credits, '_budget', lambda *a: {'has_access': True, 'limit': 0})
    monkeypatch.setattr(credits, 'balance', lambda *a: pytest.fail('Admission must not reject free work on balance'))
    class Conn:
        def close(self): pass
    credits.ensure_access('fixture', conn_factory=Conn)


def test_historical_assignment_snapshot_and_custom_catalog(owner_db, tenant, test_price):
    tid, _ = tenant
    key, _ = test_price
    now = datetime.now(timezone.utc)
    with owner_db.cursor() as cur:
        cur.execute("INSERT INTO usage_plan_limits(plan_key,feature_code,limit_value) VALUES(%s,'web_searches',500)", (key,))
        cur.execute("INSERT INTO tenant_plan_assignments(tenant_id,plan_key,status,current_period_start,current_period_end,source) VALUES(%s,%s,'trialing',%s,%s,'manual')", (tid, key, now.date(), (now + timedelta(days=14)).date()))
        cur.execute('SELECT catalog_snapshot FROM tenant_plan_assignments WHERE tenant_id=%s', (tid,))
        saved = cur.fetchone()[0]
    assert saved is not None
    assert 'web_searches' not in {f['featureCode'] for f in custom_offers.feature_catalog(owner_db)}
    # A legacy snapshot is deliberately kept in the original persisted format.
    legacy = deepcopy(saved)
    plan = usage.get_plan(owner_db, tid)
    assert plan['features']['web_searches']['limit'] == 500
    assert service._classify_rights_change(plan, {**plan, 'features': {k:v for k,v in plan['features'].items() if k!='web_searches'}}) == ('unchanged', ())
    with owner_db.cursor() as cur:
        cur.execute('SELECT catalog_snapshot FROM tenant_plan_assignments WHERE tenant_id=%s', (tid,))
        assert cur.fetchone()[0] == legacy


def test_restricted_role_cannot_bypass_retirement_wrappers(owner_db):
    with owner_db.cursor() as cur:
        for signature in ('billing_owner_catalog_command_before_search_retirement(jsonb)',
                          'billing_owner_standard_plan_create_before_search_retirement(jsonb)',
                          'billing_custom_quote_command_before_search_retirement(text,jsonb)'):
            cur.execute('SELECT has_function_privilege(%s,%s,%s)', ('ceopro_app', signature, 'EXECUTE'))
            assert cur.fetchone()[0] is False


def test_new_manual_custom_search_allowance_is_rejected(owner_db, tenant):
    with pytest.raises(admin.AdminError, match='retired'):
        admin.set_custom_contract(owner_db, tenant_id=tenant[0], contract_ref='synthetic',
                                  approved_by='fixture', reason='fixture', limits={'web_searches': 5})


def test_legacy_custom_draft_remains_tenant_scoped_and_can_carry_unchanged_limits(
        owner_db, quote_actors, billing_connections):
    from psycopg2.extras import Json
    from psycopg2 import errors
    a = quote_actors
    body = dict(tenant_id=a['tenant_a'], customer_user_id=a['user_a'],
                idempotency_key='legacy-' + uuid4().hex, request_fingerprint=uuid4().hex,
                configuration={}, feature_quantities={'web_searches': 10, 'ai_credits': 5},
                commercial_terms={}, economic_inputs={}, fx_evidence={})
    body['request_fingerprint'] = custom_offers._canonical_fingerprint(body)
    # Installation authority seeds pre-deprecation history in the disposable DB.
    with owner_db.cursor() as cur:
        cur.execute("SELECT set_config('app.current_tenant_id',%s,false),set_config('app.current_user_id',%s,false)",
                    (a['platform_tenant'], a['platform_user']))
        cur.execute('SELECT billing_custom_quote_command_before_search_retirement(%s,%s)',
                    ('create_draft', Json(body)))
        quote = cur.fetchone()[0]
    owner = _conn(billing_connections, a)
    customer = _conn(billing_connections, a, 'tenant_a')
    other = _conn(billing_connections, a, 'tenant_b')
    try:
        detail = custom_offers.quote_detail(customer, str(quote['quote_id']))
        assert detail['feature_quantities'] == body['feature_quantities']
        assert custom_offers.quote_detail(other, str(quote['quote_id'])) is None
        revision_key = 'revision-' + uuid4().hex
        revision = custom_offers.create_revision(owner, quote_id=str(quote['quote_id']), expected_revision=1,
            idempotency_key=revision_key, configuration={},
            feature_quantities=body['feature_quantities'], commercial_terms={}, economic_inputs={}, fx_evidence={})
        owner.commit()
        assert revision['revision_number'] == 2
        custom_offers.create_revision(owner, quote_id=str(quote['quote_id']), expected_revision=2,
            idempotency_key='remove-' + uuid4().hex, configuration={}, feature_quantities={'ai_credits': 5},
            commercial_terms={}, economic_inputs={}, fx_evidence={})
        owner.commit()
        replay = custom_offers.create_revision(owner, quote_id=str(quote['quote_id']), expected_revision=1,
            idempotency_key=revision_key, configuration={}, feature_quantities=body['feature_quantities'],
            commercial_terms={}, economic_inputs={}, fx_evidence={})
        owner.commit()
        assert replay['idempotent'] is True and replay['revision_id'] == revision['revision_id']
        assert custom_offers.admin_quote_detail(owner, str(quote['quote_id']))['currentRevision']['revisionNumber'] == 3
        with pytest.raises(custom_offers.CustomOfferError) as conflict:
            custom_offers.create_revision(owner, quote_id=str(quote['quote_id']), expected_revision=1,
                idempotency_key=revision_key, configuration={}, feature_quantities={'web_searches': 11, 'ai_credits': 5},
                commercial_terms={}, economic_inputs={}, fx_evidence={})
        assert conflict.value.code == 'quote_conflict'
        owner.rollback()
        with pytest.raises(errors.InvalidParameterValue):
            with owner.cursor() as cur:
                cur.execute('SELECT billing_custom_quote_command(%s,%s)', ('create_draft', Json(body)))
        owner.rollback()
        with pytest.raises(custom_offers.CustomOfferError):
            custom_offers.create_revision(owner, quote_id=str(quote['quote_id']), expected_revision=3,
                idempotency_key='new-' + uuid4().hex, configuration={},
                feature_quantities={'web_searches': 11}, commercial_terms={}, economic_inputs={}, fx_evidence={})
        with owner_db.cursor() as cur:
            cur.execute('SELECT feature_quantities FROM billing_custom_quote_revisions WHERE revision_id=%s', (quote['revision_id'],))
            assert cur.fetchone()[0] == body['feature_quantities']
    finally:
        owner.close(); customer.close(); other.close()
        with owner_db.cursor() as cur:
            cur.execute("SELECT set_config('app.current_tenant_id','',false),set_config('app.current_user_id','',false)")
