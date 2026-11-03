"""Real parser/review/repair policy; explicit offline LLM transport responses."""
import json

import pytest

from src.ai.marketing import content_generator as cg


def draft(text, hashtags=None):
    return json.dumps({'audience_summary': 'Suggested audience', 'creative_direction': 'Simple setting',
                       'platforms': {'INSTAGRAM': [{'headline': 'A moment', 'body_copy': text,
                                                   'hashtags': hashtags or [], 'cta': 'Explore'}]}}, ensure_ascii=False)


def review(claims=None, **overrides):
    return json.dumps({'supported': True, 'unsupported_claims': [], 'claims': claims or [], **overrides}, ensure_ascii=False)


def run(monkeypatch, source, copy, audit, **kwargs):
    responses = iter([draft(copy), audit])
    monkeypatch.setattr(cg.llm_client, 'chat_completion', lambda *a, **k: next(responses))
    return cg.generate_campaign_content(source, platforms=['INSTAGRAM'], **kwargs)


@pytest.mark.parametrize('language,copy', [('en', 'Explore NovaCup.'), ('ar', 'استكشف نوفاكَب.')])
def test_grounded_english_and_arabic_pass(monkeypatch, language, copy):
    claim = 'NovaCup' if language == 'en' else 'نوفاكَب'
    result = run(monkeypatch, 'Product name: NovaCup.', copy,
                 review([{'claim': claim, 'source_quote': 'NovaCup'}]), language=language)
    assert result.variants_by_platform['INSTAGRAM'][0].body_copy == copy


@pytest.mark.parametrize('notes,copy', [
    ('Explicit test-only 10% discount valid until 2026-12-20.', 'خصم ١٠٪ حتى ٢٠٢٦-١٢-٢٠.'),
    ('خصم ١٠٪ صالح حتى ٢٠٢٦-١٢-٢٠.', 'خصم 10% حتى 2026-12-20.'),
])
def test_explicit_notes_discount_and_date_are_shared_source(monkeypatch, notes, copy):
    source = cg._grounding_source('NovaCup.', notes)
    calls = []
    answers = iter([draft(copy), review()])
    def completion(messages, **kwargs):
        calls.append(messages)
        return next(answers)
    monkeypatch.setattr(cg.llm_client, 'chat_completion', completion)
    result = cg.generate_campaign_content('NovaCup.', custom_creative_prompt=notes, language='ar', platforms=['INSTAGRAM'])
    assert result.variants_by_platform['INSTAGRAM'][0].body_copy == copy
    assert source in calls[0][1]['content']
    assert json.loads(calls[1][-1]['content'])['SOURCE'] == source


def test_creative_notes_never_authorize_origin_or_certification():
    source = cg._grounding_source('Cup.', 'Audience: Amman. Imagine an organic Amman-made cup. Discount 10% until 2026-12-20.')
    assert 'Amman' not in source and 'organic' not in source
    assert '10%' in source and '2026-12-20' in source


@pytest.mark.parametrize('notes', ['Do not invent a 10% discount until 2026-12-20.',
                                 'Imagine a 10% discount until 2026-12-20.',
                                 'لا يوجد خصم ١٠٪ حتى ٢٠٢٦-١٢-٢٠.'])
def test_negative_or_hypothetical_notes_do_not_supply_campaign_facts(notes):
    assert cg._grounding_source('Cup.', notes) == 'Cup.'


def test_deadline_terms_are_canonical_but_a_start_date_is_not_an_expiry():
    assert 'Explicit campaign deadline: 2026-12-20' in cg._grounding_source('Cup.', 'Offer valid until 2026-12-20.')
    assert cg._grounding_source('Cup.', 'Campaign starts on 2026-12-20.') == 'Cup.'


@pytest.mark.parametrize('copy', ['Get 50% off.', 'Only today: NovaCup.', 'كمية محدودة من نوفاكب.',
                                  'عرض لفترة محدودة.', 'Offer ends 2026-12-21.', '10% discount.'])
def test_optimistic_review_cannot_authorize_discount_date_or_urgency(monkeypatch, copy):
    # A material percentage is not a discount fact.
    answers = iter([draft(copy), review(), draft(copy), review()])
    monkeypatch.setattr(cg.llm_client, 'chat_completion', lambda *a, **k: next(answers))
    with pytest.raises(cg.MarketingGenerationError):
        cg.generate_campaign_content('NovaCup contains 10% recycled material.', platforms=['INSTAGRAM'])


def test_repair_removes_unsupported_claim_but_keeps_supported_terms(monkeypatch):
    bad = 'Only today: 10% discount.'
    good = '10% discount until 2026-12-20.'
    answers = iter([draft(bad), review(supported=False, unsupported_claims=['Only today']), draft(good), review()])
    calls = []
    def completion(messages, **kwargs):
        calls.append(messages)
        return next(answers)
    monkeypatch.setattr(cg.llm_client, 'chat_completion', completion)
    result = cg.generate_campaign_content('NovaCup.', custom_creative_prompt='10% discount valid until 2026-12-20.', platforms=['INSTAGRAM'])
    assert result.variants_by_platform['INSTAGRAM'][0].body_copy == good
    assert len(calls) == 4
    assert 'Preserve their exact values and timing' in calls[2][-1]['content']


def test_unicode_citation_typography_is_accepted_but_invented_quote_is_not(monkeypatch):
    result = run(monkeypatch, 'خصم ١٠٪.', 'خصم 10%.', review([{'claim': '10%', 'source_quote': '١٠%'}]))
    assert '10%' in result.variants_by_platform['INSTAGRAM'][0].body_copy
    answers = iter([draft('50% off.'), review([{'claim': '50%', 'source_quote': '50%'}])]*2)
    monkeypatch.setattr(cg.llm_client, 'chat_completion', lambda *a, **k: next(answers))
    with pytest.raises(cg.MarketingGenerationError):
        cg.generate_campaign_content('NovaCup.', platforms=['INSTAGRAM'])


def test_hashtags_are_optional_in_current_output_contract(monkeypatch):
    result = run(monkeypatch, 'NovaCup.', 'A creative moment.', review())
    assert result.variants_by_platform['INSTAGRAM'][0].hashtags == []


def test_reviewer_cannot_list_source_facts_absent_from_the_draft(monkeypatch):
    answers = iter([draft('A creative moment.'), review([
        {'claim': 'stainless steel', 'source_quote': 'stainless steel'}])]*2)
    monkeypatch.setattr(cg.llm_client, 'chat_completion', lambda *a, **k: next(answers))
    with pytest.raises(cg.MarketingGenerationError):
        cg.generate_campaign_content('A stainless steel cup.', platforms=['INSTAGRAM'])


def test_second_review_gets_actionable_citation_feedback_without_relaxing_checks(monkeypatch):
    answers = iter([draft('Explore NovaCup.'), review([{'claim': 'a steel cup', 'source_quote': 'a steel cup'}]),
                    review([{'claim': 'NovaCup', 'source_quote': 'NovaCup'}])])
    calls = []
    def completion(messages, **kwargs):
        calls.append(messages)
        return next(answers)
    monkeypatch.setattr(cg.llm_client, 'chat_completion', completion)
    cg.generate_campaign_content('NovaCup is a steel cup.', platforms=['INSTAGRAM'])
    assert len(calls) == 3
    assert calls[2][0]['content'] == cg._GROUNDING_PROMPT
    assert json.loads(calls[1][-1]['content'])['DRAFT'] == json.loads(calls[2][-1]['content'])['DRAFT']
    second_input = json.loads(calls[2][-1]['content'])
    assert 'CURRENT DRAFT' in second_input['REVIEW_CONTRACT_CORRECTION']
    assert 'PREVIOUS_REJECTION_FEEDBACK' not in second_input
    assert 'a steel cup' not in second_input['REVIEW_CONTRACT_CORRECTION']


@pytest.mark.parametrize('copy', [
    'NovaCup: effortless everyday elegance. Your daily companion.',
    'Imagine this blue NovaCup on your desk during harvest season. A crisp, mindful sip.',
    'نوفاكب: رفيقك اليومي. تخيل لحظة هادئة خلال موسم القطاف.',
])
def test_creative_wording_is_not_rewritten_when_review_lists_absent_source_facts(monkeypatch, copy):
    claim = 'نوفاكب' if copy.startswith('نوفاكب') else 'NovaCup'
    answers = iter([draft(copy), review(supported=False, unsupported_claims=['330 ml capacity']),
                    review([{'claim':claim, 'source_quote':'NovaCup'}])])
    calls = []
    def completion(messages, **kwargs):
        calls.append(messages)
        return next(answers)
    monkeypatch.setattr(cg.llm_client, 'chat_completion', completion)
    result = cg.generate_campaign_content('NovaCup is a blue, 330 ml steel cup.', platforms=['INSTAGRAM'],
                                          language='ar' if claim=='نوفاكب' else 'en')
    assert result.variants_by_platform['INSTAGRAM'][0].body_copy == copy
    assert len(calls) == 3 and calls[2][0]['content'] == cg._GROUNDING_PROMPT
    assert 'REVIEW_CONTRACT_CORRECTION' in json.loads(calls[2][-1]['content'])


def test_explicit_offer_and_natural_date_survive_reviewer_citation_repair(monkeypatch):
    copy = 'NovaCup: 10% off until Dec 20.'
    answers = iter([draft(copy), review([{'claim':'2026-12-20','source_quote':'2026-12-20'}]),
                    review([{'claim':'10%','source_quote':'Explicit campaign discount: 10%'},
                            {'claim':'Dec 20','source_quote':'Explicit campaign deadline: 2026-12-20'}])])
    monkeypatch.setattr(cg.llm_client, 'chat_completion', lambda *a, **k: next(answers))
    result = cg.generate_campaign_content('NovaCup.', custom_creative_prompt='10% discount valid until 2026-12-20.',
                                          platforms=['INSTAGRAM'])
    assert result.variants_by_platform['INSTAGRAM'][0].body_copy == copy


def test_two_invalid_reviews_never_become_an_approval(monkeypatch):
    calls = []
    answers = iter([draft('A creative moment.'), review(supported=False,unsupported_claims=['330 ml capacity']),
                    review(supported=False,unsupported_claims=['330 ml capacity'])])
    def completion(messages, **kwargs):
        calls.append(messages)
        return next(answers)
    monkeypatch.setattr(cg.llm_client, 'chat_completion', completion)
    with pytest.raises(cg.MarketingGenerationError):
        cg.generate_campaign_content('Cup, 330 ml capacity.',platforms=['INSTAGRAM'])
    assert len(calls) == 3


@pytest.mark.parametrize('copy', ['Safe for every liquid.', 'آمن لكل السوائل.'])
def test_valid_reviewer_rejection_of_unsupported_compatibility_still_fails(monkeypatch, copy):
    rejection = review(supported=False, unsupported_claims=[copy])
    answers = iter([draft(copy), rejection, draft(copy), rejection])
    monkeypatch.setattr(cg.llm_client, 'chat_completion', lambda *a, **k: next(answers))
    with pytest.raises(cg.MarketingGenerationError):
        cg.generate_campaign_content('NovaCup.', platforms=['INSTAGRAM'])


def test_repaired_draft_review_never_receives_obsolete_rejected_claims(monkeypatch):
    bad = 'NovaCup keeps drinks at the perfect temperature.'
    good = 'NovaCup: your daily companion.'
    answers = iter([draft(bad), review(supported=False,unsupported_claims=[bad]),
                    draft(good), review([{'claim':'NovaCup','source_quote':'NovaCup'}])])
    calls = []
    def completion(messages, **kwargs):
        calls.append(messages)
        return next(answers)
    monkeypatch.setattr(cg.llm_client, 'chat_completion', completion)
    result = cg.generate_campaign_content('NovaCup is a reusable cup.',platforms=['INSTAGRAM'])
    assert result.variants_by_platform['INSTAGRAM'][0].body_copy == good
    assert bad in calls[2][-1]['content']  # only the writer gets removal details
    assert bad not in json.dumps(calls[3],ensure_ascii=False)
    assert set(json.loads(calls[3][-1]['content'])) == {'SOURCE','DRAFT'}


@pytest.mark.parametrize('response', ['[]', '{}', '{"supported":true,"claims":[null],"unsupported_claims":[]}'])
def test_malformed_review_still_fails_closed(monkeypatch, response):
    answers = iter([draft('A moment.'), response]*2)
    monkeypatch.setattr(cg.llm_client, 'chat_completion', lambda *a, **k: next(answers))
    with pytest.raises(cg.MarketingGenerationError):
        cg.generate_campaign_content('NovaCup.', platforms=['INSTAGRAM'])
