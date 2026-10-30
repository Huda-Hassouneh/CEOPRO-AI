"""Confirmed acceptance defects: scope selection and unsupported ad claims."""
import json
from unittest.mock import patch

import pytest

from src.ai.rag import understanding
from src.ai.marketing import content_generator as cg


@pytest.mark.parametrize('question',[
    'Which product has the highest revenue across all our sales history?',
    'What is our all-time sales revenue?',
    'Which product leads across all of our sales history?',
    'Show lifetime sales revenue',
    'ما المنتج الأعلى إيراداً عبر كامل سجل المبيعات؟',
])
def test_all_history_is_an_explicit_scope(question):
    assert understanding.understand(question).slots.get('all_history') is True


def test_all_history_followup_replaces_previous_day_window():
    previous=understanding.understand('Show sales in the last 90 days').state()
    slots=understanding.understand('And across all history?',previous=previous).slots
    assert slots.get('all_history') is True and 'period_days' not in slots


def test_changed_scope_reranks_an_implicitly_resolved_top_product():
    previous=understanding.understand('Which is my top product in the last 90 days?').state()
    previous['slots']['top_product']=True
    previous['slots']['products']=[{'product_id':'recent-winner','name':'Recent winner'}]
    slots=understanding.understand('And across all history?',previous=previous).slots
    assert slots['top_product'] is True and 'products' not in slots


def _copy(text):
    return json.dumps({'audience_summary':'Home cooks might enjoy this product.',
        'creative_direction':'Warm lighting on a pantry shelf.',
        'platforms':{'INSTAGRAM':[{'headline':'A pantry moment','body_copy':text,'hashtags':[],'cta':'Explore'}]}})


def test_unverified_origin_never_returns_as_completed_copy():
    with patch.object(cg.llm_client,'chat_completion',return_value=_copy("Crafted from Amman's finest olives and bottled right here in Amman.")):
        with pytest.raises(cg.MarketingGenerationError):
            cg.generate_campaign_content('Extra Virgin Olive Oil 1L. Price 9.500 JOD.',focus='Amman harvest pantry',platforms=['INSTAGRAM'])


def test_optimistic_review_cannot_authorize_an_unsourced_origin():
    review=json.dumps({'supported':True,'unsupported_claims':[],'claims':[]})
    with patch.object(cg.llm_client,'chat_completion',side_effect=[_copy('Bottled in Amman.'),review]*2):
        with pytest.raises(cg.MarketingGenerationError):
            cg.generate_campaign_content('Olive oil 1L.',platforms=['INSTAGRAM'])


def test_treat_yourself_hook_is_not_a_medical_claim():
    review=json.dumps({'supported':True,'unsupported_claims':[],'claims':[]})
    with patch.object(cg.llm_client,'chat_completion',side_effect=[_copy('Treat yourself to a pantry moment.'),review]):
        result=cg.generate_campaign_content('Olive oil 1L.',platforms=['INSTAGRAM'])
    assert result.variants_by_platform['INSTAGRAM'][0].body_copy.startswith('Treat yourself')


def test_explicit_recent_followup_replaces_all_history():
    previous=understanding.understand('Show all-time sales').state()
    slots=understanding.understand('And the last 30 days?',previous=previous).slots
    assert slots['period_days']==30 and 'all_history' not in slots


@pytest.mark.parametrize('unsupported',[
    'Bottled in Amman.', 'Certified organic and cures inflammation.',
    'مصنوع من زيتون عمان وحاصل على شهادة عضوية.',
])
def test_unsupported_claims_are_repaired_once_then_refused(unsupported):
    audit=json.dumps({'supported':False,'unsupported_claims':[unsupported],'claims':[]})
    with patch.object(cg.llm_client,'chat_completion',side_effect=[_copy(unsupported),audit,_copy(unsupported),audit]) as call:
        with pytest.raises(cg.MarketingGenerationError):
            cg.generate_campaign_content('Olive oil 1L.',platforms=['INSTAGRAM'])
        assert call.call_count==4


def test_source_quotes_are_checked_and_creative_hooks_survive():
    bad=json.dumps({'supported':True,'unsupported_claims':[],
                    'claims':[{'claim':'Bottled in Amman.','source_quote':'Bottled in Amman.'}]})
    good=json.dumps({'supported':True,'unsupported_claims':[],
                     'claims':[{'claim':'Olive oil 1L.','source_quote':'Olive oil 1L.'}]})
    with patch.object(cg.llm_client,'chat_completion',side_effect=[_copy('Bottled in Amman.'),bad,_copy('A pantry moment. Olive oil 1L.'),good]):
        result=cg.generate_campaign_content('Olive oil 1L.',focus='Amman harvest pantry',platforms=['INSTAGRAM'])
    assert result.variants_by_platform['INSTAGRAM'][0].body_copy=='A pantry moment. Olive oil 1L.'


def test_review_can_identify_a_supported_brand_written_as_a_hashtag():
    payload=json.loads(_copy('A pantry moment.'))
    payload['platforms']['INSTAGRAM'][0]['hashtags']=['#ZaytounaDemo']
    review=json.dumps({'supported':True,'unsupported_claims':[],
                     'claims':[{'claim':'Zaytouna Demo','source_quote':'Brand: Zaytouna Demo'}]})
    with patch.object(cg.llm_client,'chat_completion',side_effect=[json.dumps(payload),review]):
        result=cg.generate_campaign_content('Brand: Zaytouna Demo',platforms=['INSTAGRAM'])
    assert result.variants_by_platform['INSTAGRAM'][0].hashtags==['#ZaytounaDemo']


def test_arabic_factual_span_uses_original_draft_language_and_source_quote():
    review=json.dumps({'supported':True,'unsupported_claims':[],
                      'claims':[{'claim':'زيت الزيتون البكر الممتاز','source_quote':'Extra Virgin Olive Oil 1L'}]})
    with patch.object(cg.llm_client,'chat_completion',side_effect=[_copy('استكشف زيت الزيتون البكر الممتاز اليوم.'),review]):
        result=cg.generate_campaign_content('Extra Virgin Olive Oil 1L',platforms=['INSTAGRAM'],language='ar')
    assert 'زيت الزيتون' in result.variants_by_platform['INSTAGRAM'][0].body_copy


def test_reviewer_failure_is_not_an_unreviewed_success():
    with patch.object(cg.llm_client,'chat_completion',side_effect=[_copy('A pantry moment.'),cg.llm_client.LLMError('unavailable')]):
        with pytest.raises(cg.MarketingGenerationError):
            cg.generate_campaign_content('Olive oil 1L.',platforms=['INSTAGRAM'])


def test_draft_and_factual_review_both_accumulate_actual_token_usage():
    review=json.dumps({'supported':True,'unsupported_claims':[],'claims':[]})
    usage={}
    with patch.object(cg.llm_client,'_chat_completion_with_usage',side_effect=[
        (_copy('A pantry moment.'),{'total_tokens':123}), (review,{'total_tokens':34})]) as complete:
        cg.generate_campaign_content('Olive oil 1L.',platforms=['INSTAGRAM'],usage_out=usage)
    assert usage['total_tokens']==157
    assert all(call.kwargs['json_mode'] is True for call in complete.call_args_list)


def test_all_history_gathering_does_not_add_recent_default_sections(monkeypatch):
    from src.ai.rag import advisor, evidence, access
    monkeypatch.setattr(advisor,'build_fact_sections',lambda *a,**k:pytest.fail('recent facts must not be queried'))
    monkeypatch.setattr(advisor,'build_historical_sales_lines',lambda *a:['All stored history:','- 4L oil revenue 33132 JOD.'])
    u=understanding.understand('Which product has the highest revenue across all our sales history?')
    registry=evidence.EvidenceRegistry()
    assert advisor._fact_sections(object(),'tenant',u,access.FULL_ACCESS,registry,[])>0
    assert advisor._fact_sections(object(),'tenant',u,access.for_role('staff'),evidence.EvidenceRegistry(),[])==0
