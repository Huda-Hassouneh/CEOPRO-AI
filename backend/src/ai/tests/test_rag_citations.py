"""Claim-level citation checks (rag/citations.py): only what the evidence
supports reaches the user, and every reference is numbered from real evidence."""
import json

from src.ai.rag import citations as c
from src.ai.rag import evidence as ev


def _registry():
    registry = ev.EvidenceRegistry()
    registry.add(ev.COMPANY_RECORD, "Sales in the last 30 days", "Revenue 20016.928 JOD from 3000 invoices; the 30 days "
                 "before: 20236.863 JOD.", ev.COMPANY, ev.OBSERVED, route="/sales")
    registry.add(ev.WEB_PAGE, "Customs tariff", "Olive oil (HS 1509) attracts a customs duty of 20% on import.",
                 ev.OFFICIAL, ev.EXTRACTED, url="https://customs.gov.jo/tariff", jurisdiction="JO")
    registry.add(ev.WEB_PAGE, "Trade blog", "Importers say the duty on olive oil is about 20 percent.", ev.SECONDARY,
                 ev.EXTRACTED, url="https://blog.example.com/olive-oil")
    return registry


def _draft(*claims):
    return c.Draft(blocks=[{"type": "paragraph", "claims": [c.Claim(text, kind, ids) for text, kind, ids in claims]}])


def test_a_figure_copied_from_its_evidence_passes():
    draft, issues = c.validate(_draft(("Revenue was 20,016.928 JOD in the last 30 days.", c.FACT, ["E1"])), _registry())
    assert issues == []
    assert draft.blocks[0]["claims"][0].verified


def test_a_figure_not_in_its_evidence_is_removed():
    draft, issues = c.validate(_draft(("Revenue was 25,000 JOD.", c.FACT, ["E1"]),
                                      ("Sales held steady.", c.INFERENCE, ["E1"])), _registry())
    texts = [claim.text for claim in draft.blocks[0]["claims"]]
    assert texts == ["Sales held steady."]
    assert "25000" in issues[0].problem or "25,000" in issues[0].problem or "25000" in issues[0].claim.replace(",", "")


def test_a_figure_from_a_different_item_than_the_one_cited_is_not_supported():
    # 20% is in E2, but the claim cites only the sales record.
    draft, issues = c.validate(_draft(("The duty is 20%.", c.FACT, ["E1"])), _registry())
    assert not draft.blocks and issues


def test_rounding_and_arabic_digits_are_accepted():
    registry = _registry()
    draft, issues = c.validate(_draft(("الإيرادات ٢٠٠١٦٫٩٣ دينار.", c.FACT, ["E1"]),
                                      ("Revenue was about 20,000 JOD.", c.FACT, ["E1"])), registry)
    assert issues == [] and len(draft.blocks[0]["claims"]) == 2


def test_a_difference_or_percentage_of_two_cited_figures_counts_as_a_calculation():
    draft, issues = c.validate(_draft(("Revenue fell by 219.935 JOD.", c.FACT, ["E1"]),
                                      ("That is a 1.09% drop.", c.FACT, ["E1"])), _registry())
    assert issues == []
    rendered = c.render(draft, _registry())
    assert [claim["kind"] for claim in rendered["blocks"][0]["claims"]] == [c.CALCULATION, c.CALCULATION]


def test_a_wrong_difference_is_caught():
    # 20236.863 - 20016.928 = 219.935, not 1819.935 (a real model error seen in testing)
    draft, issues = c.validate(_draft(("Revenue fell by 1,819.935 JOD.", c.CALCULATION, ["E1"])), _registry())
    assert not draft.blocks and issues


def test_unknown_evidence_ids_are_dropped_and_a_fact_without_evidence_is_marked_unverified():
    draft, issues = c.validate(_draft(("Customers love the packaging.", c.FACT, ["E99"])), _registry())
    claim = draft.blocks[0]["claims"][0]
    assert claim.evidence == [] and not claim.verified and "no_evidence" in claim.notes
    assert any("E99" in issue.problem for issue in issues)


def test_a_link_must_belong_to_the_cited_source():
    draft, _ = c.validate(_draft(("See https://evil.example.com/x for the tariff.", c.FACT, ["E2"])), _registry())
    assert "evil.example.com" not in draft.blocks[0]["claims"][0].text


def test_a_quotation_must_appear_in_the_cited_excerpt():
    draft, _ = c.validate(_draft(('The authority says "olive oil is exempt from all customs duty".', c.FACT, ["E2"]),
                                 ('The tariff says "attracts a customs duty of 20% on import".', c.FACT, ["E2"])), _registry())
    first, second = draft.blocks[0]["claims"]
    assert not first.verified and "quotation_not_found" in first.notes
    assert second.verified


def test_legal_statements_resting_only_on_unofficial_sources_are_flagged():
    draft, _ = c.validate(_draft(("Import duty on olive oil is 20%.", c.FACT, ["E3"]),
                                 ("Import duty on olive oil is 20%.", c.FACT, ["E2"])), _registry(), regulatory=True)
    unofficial, official = draft.blocks[0]["claims"]
    assert "unofficial_source" in unofficial.notes
    assert "unofficial_source" not in official.notes


def test_numbers_in_a_table_are_checked_against_its_evidence():
    draft = c.Draft(blocks=[{"type": "table", "columns": ["Period", "Revenue"], "evidence": ["E1"],
                             "rows": [["Last 30 days", "20016.928"], ["Before", "99999"]]}])
    checked, issues = c.validate(draft, _registry())
    assert checked.blocks[0]["rows"] == [["Last 30 days", "20016.928"]] and issues


def test_references_are_numbered_in_order_of_first_use_and_reused():
    registry = _registry()
    draft, _ = c.validate(_draft(("The duty is 20%.", c.FACT, ["E2"]),
                                 ("Revenue was 20,016.928 JOD.", c.FACT, ["E1"]),
                                 ("The duty applies on import.", c.FACT, ["E2"])), registry)
    rendered = c.render(draft, registry)
    assert [claim["refs"] for claim in rendered["blocks"][0]["claims"]] == [[1], [2], [1]]
    assert [ref["evidence_id"] for ref in rendered["references"]] == ["E2", "E1"]
    assert rendered["references"][0]["url"] == "https://customs.gov.jo/tariff"
    assert rendered["answer"].count("¹") == 2 and "²" in rendered["answer"]
    assert c.plain_text(rendered["answer"]).count("¹") == 0


def test_a_cited_calculation_also_references_its_sourced_inputs():
    registry = _registry()
    user = registry.add(ev.USER_INPUT, "Your message", "freight 300 JOD", ev.USER, ev.USER_PROVIDED)
    step = registry.add(ev.CALCULATION, "Customs duty", "Customs duty = customs value × duty rate = 494.000 JOD",
                        ev.CALCULATED, ev.CALCULATED_STATUS, data={"input_evidence": [user.id, "E2"]})
    total = registry.add(ev.CALCULATION, "Landed cost", "Landed cost = 3,588.240 JOD", ev.CALCULATED,
                         ev.CALCULATED_STATUS, data={"input_evidence": [step.id]})
    draft, _ = c.validate(_draft(("The landed cost is 3,588.24 JOD.", c.CALCULATION, [total.id])), registry)
    rendered = c.render(draft, registry)
    calc_ref = rendered["references"][0]
    assert calc_ref["evidence_id"] == total.id
    inputs = {ref["evidence_id"]: ref for ref in rendered["references"][1:]}
    assert set(inputs) == {user.id, "E2"}
    assert sorted(calc_ref["input_refs"]) == sorted(ref["n"] for ref in inputs.values())
    assert all(ref["used_as"] == ["calculation_input"] for ref in inputs.values())


def test_always_referenced_evidence_gets_a_number_even_when_not_cited():
    registry = _registry()
    draft, _ = c.validate(_draft(("Revenue was 20,016.928 JOD.", c.FACT, ["E1"])), registry)
    rendered = c.render(draft, registry, always=["E2"])
    assert rendered["numbering"] == {"E1": 1, "E2": 2}


def test_parse_draft_accepts_the_format_and_rejects_anything_else():
    raw = json.dumps({"blocks": [{"type": "heading", "text": "Sales"},
                                 {"type": "paragraph", "claims": [{"text": "x", "kind": "fact", "evidence": ["E1"]}]},
                                 {"type": "list", "items": [[{"text": "y", "kind": "recommendation", "evidence": "E1, E2"}]]}],
                      "follow_up_questions": ["a", "b", "c", "d"]})
    draft = c.parse_draft("Here you go:\n" + raw)
    assert [b["type"] for b in draft.blocks] == ["heading", "paragraph", "list"]
    assert draft.blocks[2]["items"][0][0].evidence == ["E1", "E2"]
    assert len(draft.follow_up_questions) == 3
    assert c.parse_draft("plain text answer") is None
    assert c.parse_draft('{"blocks": [{"type": "heading", "text": "only a heading"}]}') is None
    assert c.parse_draft("{not json") is None


def test_a_paragraph_written_as_plain_text_cites_nothing_and_its_figures_fail():
    draft = c.parse_draft('{"blocks": [{"type": "paragraph", "text": "Revenue was 777 JOD."}]}')
    checked, issues = c.validate(draft, _registry())
    assert not checked.blocks and issues


def _long_draft(**extra):
    claims = [c.Claim(text=f"Sentence number {n} says something about the product range and its prices.",
                      kind=c.FACT, evidence=[]) for n in range(8)]
    return c.Draft(blocks=[{"type": "paragraph", "claims": claims}], **extra)


def test_a_long_answer_gets_a_short_summary_and_a_short_one_does_not():
    registry = ev.EvidenceRegistry()
    assert c.render(_long_draft(), registry)["summary"] is not None
    short = c.Draft(blocks=[{"type": "paragraph", "claims": [c.Claim("Net 45 days.", c.GENERAL, [])]}])
    assert c.render(short, registry)["summary"] is None


def test_the_fallback_summary_is_the_first_statements_never_a_greeting():
    registry = ev.EvidenceRegistry()
    draft = _long_draft()
    draft.blocks[0]["claims"].insert(0, c.Claim("Hi there!", c.GENERAL, []))
    summary = c.render(draft, registry)["summary"]
    assert summary["text"].startswith("Sentence number 0") and "Hi there" not in summary["text"]
    assert len(summary["claims"]) <= c.SUMMARY_MAX_CLAIMS


def test_the_models_own_summary_is_parsed_checked_numbered_first_and_never_triggers_a_repair():
    registry = ev.EvidenceRegistry()
    first = registry.add(ev.COMPANY_RECORD, "Sales", "Revenue was 500 JOD", ev.COMPANY, ev.OBSERVED)
    second = registry.add(ev.COMPANY_RECORD, "Costs", "Costs were 300 JOD", ev.COMPANY, ev.OBSERVED)
    raw = json.dumps({"summary": [{"text": "Revenue was 999 JOD.", "kind": "fact", "evidence": [first.id]}],
                      "blocks": [{"type": "paragraph", "claims": [
                          {"text": "Costs were 300 JOD." + " More detail." * 30, "kind": "fact", "evidence": [second.id]}]}]})
    draft = c.parse_draft(raw)
    assert [x.text for x in draft.summary] == ["Revenue was 999 JOD."]
    checked, issues = c.validate(draft, registry)
    assert checked.summary == [] and issues == []  # the unsupported figure is dropped, not repaired
    ok = c.parse_draft(raw.replace("999", "500"))
    checked, issues = c.validate(ok, registry)
    rendered = c.render(checked, registry)
    assert rendered["summary"]["refs"] == [1]  # numbered before the detail's own reference
    assert rendered["summary"]["text"] == "Revenue was 500 JOD."


def test_a_summary_alone_is_a_complete_answer():
    registry = ev.EvidenceRegistry()
    item = registry.add(ev.COMPANY_RECORD, "Terms", "Net 45 days", ev.COMPANY, ev.OBSERVED)
    draft = c.parse_draft(json.dumps({"summary": [{"text": "Net 45 days.", "kind": "fact", "evidence": [item.id]}],
                                      "blocks": []}))
    assert draft is not None and draft.blocks[0]["claims"][0].text == "Net 45 days."


def test_the_summary_source_and_drops_are_reported_for_the_per_answer_log():
    registry = ev.EvidenceRegistry()
    first = registry.add(ev.COMPANY_RECORD, "Sales", "Revenue was 500 JOD", ev.COMPANY, ev.OBSERVED)
    detail = {"type": "paragraph", "claims": [{"text": "Revenue was 500 JOD." + " More detail." * 30, "kind": "fact",
                                                "evidence": [first.id]}]}
    good = {"text": "Revenue was 500 JOD.", "kind": "fact", "evidence": [first.id]}
    bad = {"text": "Revenue was 999 JOD.", "kind": "fact", "evidence": [first.id]}

    def rendered(summary):
        checked, _ = c.validate(c.parse_draft(json.dumps({"summary": summary, "blocks": [detail]})), registry)
        return c.render(checked, registry)

    kept = rendered([good])
    assert (kept["summary_source"], kept["summary_dropped"]) == ("model", 0)
    dropped = rendered([bad])  # falls back to the answer's own first claims
    assert (dropped["summary_source"], dropped["summary_dropped"]) == ("fallback", 1)
    assert rendered([])["summary_source"] == "fallback"
    short = c.render(_draft(("Net 45 days.", c.GENERAL, [])), _registry())
    assert (short["summary_source"], short["summary_dropped"]) == ("none", 0)
