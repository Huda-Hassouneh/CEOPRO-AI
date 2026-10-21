"""
Claim-level citations: the answer format the model must use, the checks
every claim passes before the user sees it, and the numbered references.

The model answers in JSON: blocks of claims, each claim stating what kind
of statement it is (a fact, a calculation result, an estimate, an
inference, a recommendation, an assumption, a statement that something is
unknown, or general wording such as a greeting) and the evidence ids it
rests on. validate() then checks each claim against the evidence itself,
not against the model's word:

- a cited id must exist in this question's evidence;
- every number in the claim must appear in the evidence it cites (Arabic
  or Western digits, separators and rounding allowed for), or follow from
  two of those numbers by one arithmetic step (a difference, ratio or
  percentage change), which is then labelled as calculated;
- a quotation must appear word for word in a cited excerpt;
- a link must be one of the cited sources' own links;
- facts, calculations, estimates, inferences and recommendations must cite
  something; regulatory statements resting only on unofficial sources are
  flagged as such.

A claim whose numbers are not supported is removed. A claim that cites
nothing although it should is kept but marked as not verified, so the
user can tell it apart. Nothing is ever added to an answer by these
checks - they only remove, qualify or mark.
"""
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Dict, Iterable, List, Optional, Set, Tuple

from src.ai.extraction.numerals import to_ascii_digits
from src.ai.rag import evidence as ev

FACT, CALCULATION, ESTIMATE, INFERENCE = "fact", "calculation", "estimate", "inference"
RECOMMENDATION, ASSUMPTION, UNKNOWN, GENERAL = "recommendation", "assumption", "unknown", "general"
KINDS = (FACT, CALCULATION, ESTIMATE, INFERENCE, RECOMMENDATION, ASSUMPTION, UNKNOWN, GENERAL)
NEEDS_EVIDENCE = frozenset({FACT, CALCULATION, ESTIMATE, INFERENCE, RECOMMENDATION})

DRAFT_CONTRACT = """\
Answer format (strict): reply with ONE JSON object and nothing else:
{"summary": [CLAIM, ...], "blocks": [BLOCK, ...], "follow_up_questions": ["...", ...]}
"summary" comes first: the answer itself in one or two short claims (about 40 words in all), the part most
readers will read alone. It follows every claim rule below, citing its evidence. "blocks" is the detail behind it:
add only what the summary leaves out, as little as the question needs, and leave it empty when the summary
already answers the question.
BLOCK is one of:
  {"type": "heading", "text": "..."}
  {"type": "paragraph", "claims": [CLAIM, ...]}
  {"type": "list", "ordered": false, "items": [[CLAIM, ...], [CLAIM, ...]]}
  {"type": "table", "columns": ["...", ...], "rows": [["...", ...], ...], "evidence": ["E1", ...]}
CLAIM is {"text": "one sentence", "kind": KIND, "evidence": ["E3", "E7"]}.
KIND is exactly one of: fact (stated by the evidence), calculation (a KEEL calculation result), estimate,
inference (your reasoning from the evidence), recommendation, assumption, unknown (something that could not be
established), general (greetings, wording with no factual content).
Rules for claims:
- One sentence per claim. Cite the evidence ids ([E...]) that directly support THAT sentence - never an id that
  does not say it. Facts, calculations, estimates, inferences and recommendations must cite at least one id.
- Copy numbers exactly as they appear in the evidence (you may round them). Never compute new figures yourself:
  use the KEEL calculation items. A percentage change or difference between two cited figures is the only
  arithmetic allowed.
- Never invent a source, link, date, quotation, price, rate or figure. A link may only be one given in the evidence.
- If the evidence does not establish something the user asked, say so in an "unknown" claim, and say what would
  establish it (and that KEEL tried to research it, when the research status says so).
- For legal, tax, customs or regulatory statements, name the country and cite the official source when one is
  given; if only unofficial sources were found, say so.
- For a landed-cost or other KEEL calculation: give the per-unit and total result and the comparison, cite the
  summary calculation item, name the main cost components, the break-even quantity when given, each assumption
  (as an "assumption" claim citing the calculation) and what is not included or still missing.
- "follow_up_questions": at most 3 short questions the user could ask next, or the specific details you need from
  them (only when an answer depends on them). Write them in the user's language.
"""

SUMMARY_MAX_CLAIMS = 2
# An answer this short needs no summary above it.
SUMMARY_MIN_ANSWER_CHARS = 240

_SUPERSCRIPT = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_NUMBER = re.compile(r"(?<![\w.])[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])[-+]?\d+(?:\.\d+)?")
_APPROXIMATE = re.compile(r"\b(about|around|approximately|roughly|nearly|almost|over|under|more than|less than)\b|"
                          r"(حوالي|حوالى|تقريبا|تقريباً|نحو|قرابة|أكثر من|اكثر من|أقل من|اقل من)")
_QUOTE = re.compile(r"[\"“«]([^\"”»]{15,})[\"”»]")
_URL = re.compile(r"https?://[^\s)\]>\"']+")
_LEGAL_WORDS = re.compile(r"\b(must|required|requires|mandatory|prohibited|banned|permitted|licen[cs]e|law|regulation|"
                          r"duty|tariff|vat|tax)\b|(يجب|إلزامي|الزامي|ممنوع|محظور|مسموح|ترخيص|قانون|نظام|ضريبة|رسوم|جمرك|تعرفة)",
                          re.IGNORECASE)


@dataclass
class Claim:
    text: str
    kind: str
    evidence: List[str]
    verified: bool = True
    notes: List[str] = field(default_factory=list)
    derived: bool = False


@dataclass
class Draft:
    blocks: List[dict]
    follow_up_questions: List[str] = field(default_factory=list)
    summary: List["Claim"] = field(default_factory=list)  # the short answer shown first; may be empty


@dataclass
class Issue:
    claim: str
    problem: str


def _parse_claim(raw) -> Optional[Claim]:
    if isinstance(raw, str):
        raw = {"text": raw, "kind": GENERAL, "evidence": []}
    if not isinstance(raw, dict) or not str(raw.get("text") or "").strip():
        return None
    kind = str(raw.get("kind") or GENERAL).lower().strip()
    if kind not in KINDS:
        kind = INFERENCE if raw.get("evidence") else GENERAL
    ids = raw.get("evidence") or []
    if isinstance(ids, str):
        ids = re.findall(r"E\d+", ids)
    return Claim(text=str(raw["text"]).strip(), kind=kind,
                 evidence=[str(i).strip().strip("[]") for i in ids if str(i).strip()])


def parse_draft(text: str) -> Optional[Draft]:
    """The model's JSON answer, normalised; None when it is not usable JSON."""
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except ValueError:
        return None
    raw_blocks = payload.get("blocks") if isinstance(payload, dict) else None
    if not isinstance(raw_blocks, list):
        return None
    blocks: List[dict] = []
    for raw in raw_blocks:
        if not isinstance(raw, dict):
            continue
        kind = raw.get("type")
        if kind == "heading" and str(raw.get("text") or "").strip():
            blocks.append({"type": "heading", "text": str(raw["text"]).strip()})
        elif kind == "paragraph":
            # A paragraph written as plain text cites nothing: its figures then fail the checks.
            raw_claims = raw.get("claims") or ([raw["text"]] if raw.get("text") else [])
            claims = [c for c in (_parse_claim(r) for r in raw_claims) if c]
            if claims:
                blocks.append({"type": "paragraph", "claims": claims})
        elif kind == "list":
            items = []
            for item in raw.get("items") or []:
                claims = [c for c in (_parse_claim(r) for r in (item if isinstance(item, list) else [item])) if c]
                if claims:
                    items.append(claims)
            if items:
                blocks.append({"type": "list", "ordered": bool(raw.get("ordered")), "items": items})
        elif kind == "table" and isinstance(raw.get("columns"), list) and isinstance(raw.get("rows"), list):
            columns = [str(c) for c in raw["columns"]][:8]
            rows = [[str(cell) for cell in row][:len(columns)] for row in raw["rows"] if isinstance(row, list)][:30]
            if columns and rows:
                blocks.append({"type": "table", "columns": columns, "rows": rows,
                               "evidence": [str(i) for i in raw.get("evidence") or []]})
    raw_summary = payload.get("summary")
    summary = [c for c in (_parse_claim(r) for r in (raw_summary if isinstance(raw_summary, list) else
                                                      [raw_summary] if raw_summary else [])) if c][:SUMMARY_MAX_CLAIMS]
    if not any(block["type"] != "heading" for block in blocks):
        if not summary:
            return None
        blocks.append({"type": "paragraph",  # a summary that says it all
                       "claims": [Claim(c.text, c.kind, list(c.evidence)) for c in summary]})
    questions = [str(q).strip() for q in payload.get("follow_up_questions") or [] if str(q).strip()][:3]
    return Draft(blocks=blocks, follow_up_questions=questions, summary=summary)


# --- numbers -----------------------------------------------------------------

def _to_decimal(token: str) -> Optional[Decimal]:
    try:
        return Decimal(token.replace(",", "").lstrip("+"))
    except InvalidOperation:
        return None


def numbers_in(text: str) -> List[Tuple[Decimal, int]]:
    """(value, decimal places) for every number in the text, any digit script."""
    normalized = to_ascii_digits(text or "").replace("٫", ".").replace("٬", ",")
    # Dates and times are not figures: 2026-10-16, 16/10/2026, 14:30.
    normalized = re.sub(r"\d{4}-\d{2}-\d{2}(T[\d:.+-]+Z?)?|\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}:\d{2}", " ", normalized)
    found = []
    for match in _NUMBER.finditer(normalized):
        value = _to_decimal(match.group(0))
        if value is None:
            continue
        places = len(match.group(0).split(".", 1)[1]) if "." in match.group(0) else 0
        found.append((abs(value), places))
    return found


def _rounds_to(evidence_value: Decimal, claim_value: Decimal, places: int) -> bool:
    if evidence_value == claim_value:
        return True
    quantum = Decimal(1).scaleb(-places)
    try:
        return abs(evidence_value).quantize(quantum) == claim_value
    except InvalidOperation:
        return False


def _derived(values: List[Decimal]) -> Set[Decimal]:
    out: Set[Decimal] = set()
    values = values[:40]
    for i, a in enumerate(values):
        for b in values[i + 1:]:
            out.update({a + b, abs(a - b)})
            if b:
                out.update({a / b, abs(a - b) / b * 100})
            if a:
                out.update({b / a, abs(b - a) / a * 100})
    return out


def _supported(value: Decimal, places: int, pool: List[Decimal], derived: Set[Decimal], approximate: bool) -> str:
    if any(_rounds_to(e, value, places) for e in pool):
        return "direct"
    if approximate and any(e and abs(e - value) / e <= Decimal("0.02") for e in pool):
        return "direct"
    if any(_rounds_to(d, value, places) for d in derived):
        return "derived"
    return ""


# --- validation --------------------------------------------------------------

def _evidence_numbers(items: Iterable[ev.Evidence]) -> List[Decimal]:
    pool = []
    for item in items:
        pool.extend(value for value, _ in numbers_in(f"{item.title} {item.excerpt}"))
        if item.data:
            pool.extend(value for value, _ in numbers_in(json.dumps(item.data, ensure_ascii=False)))
    return pool


def _normalise_text(text: str) -> str:
    return re.sub(r"\s+", " ", to_ascii_digits(text or "").lower()).strip()


def validate(draft: Draft, registry: ev.EvidenceRegistry, user_text: str = "",
             regulatory: bool = False) -> Tuple[Draft, List[Issue]]:
    """The draft with every claim checked against its evidence (see the
    module docstring); returns the cleaned draft and what was wrong."""
    issues: List[Issue] = []
    user_numbers = [value for value, _ in numbers_in(user_text)]

    def check(claim: Claim) -> Optional[Claim]:
        valid_ids = []
        for evidence_id in claim.evidence:
            if registry.get(evidence_id):
                valid_ids.append(evidence_id)
            else:
                issues.append(Issue(claim.text, f"cites {evidence_id}, which is not in the evidence"))
        claim.evidence = list(dict.fromkeys(valid_ids))
        cited = [registry.get(i) for i in claim.evidence]

        for url in _URL.findall(claim.text):
            if not any(item.url and url.rstrip(".,;") in (item.url, item.url.rstrip("/")) for item in cited):
                claim.text = claim.text.replace(url, "").strip()
                issues.append(Issue(claim.text, f"link {url} is not one of the cited sources"))

        numbers = [(value, places) for value, places in numbers_in(claim.text)
                   if not (places == 0 and value <= 3)]
        if numbers:
            pool = _evidence_numbers(cited)
            if claim.kind == ASSUMPTION:
                pool += user_numbers
            approximate = bool(_APPROXIMATE.search(claim.text))
            derived = _derived(pool) if pool else set()
            for value, places in numbers:
                support = _supported(value, places, pool, derived, approximate)
                if not support:
                    issues.append(Issue(claim.text, f"the number {value} is not in the evidence it cites"))
                    return None
                if support == "derived":
                    claim.derived = True

        for quote in _QUOTE.findall(claim.text):
            if not any(_normalise_text(quote) in _normalise_text(item.excerpt) for item in cited):
                claim.verified = False
                claim.notes.append("quotation_not_found")
                issues.append(Issue(claim.text, "the quoted words are not in the cited evidence"))

        if claim.kind in NEEDS_EVIDENCE and not claim.evidence:
            claim.verified = False
            claim.notes.append("no_evidence")
            issues.append(Issue(claim.text, f"a {claim.kind} claim without any evidence"))
        if regulatory and claim.evidence and _LEGAL_WORDS.search(claim.text):
            web = [item for item in cited if item.kind == ev.WEB_PAGE]
            if web and not any(item.credibility == ev.OFFICIAL for item in web):
                claim.notes.append("unofficial_source")
        return claim

    # A summary that fails its checks is dropped rather than repaired: the render falls back to the answer's
    # own first claims, so it never costs a repair round.
    checked = len(issues)
    summary = [c for c in (check(claim) for claim in draft.summary) if c and (c.evidence or c.kind in (GENERAL, UNKNOWN))]
    del issues[checked:]

    blocks: List[dict] = []
    for block in draft.blocks:
        if block["type"] == "paragraph":
            claims = [c for c in (check(claim) for claim in block["claims"]) if c]
            if claims:
                blocks.append({**block, "claims": claims})
        elif block["type"] == "list":
            items = [[c for c in (check(claim) for claim in item) if c] for item in block["items"]]
            items = [item for item in items if item]
            if items:
                blocks.append({**block, "items": items})
        elif block["type"] == "table":
            ids = [i for i in block.get("evidence") or [] if registry.get(i)]
            pool = _evidence_numbers(registry.get(i) for i in ids)
            derived = _derived(pool) if pool else set()
            rows = []
            for row in block["rows"]:
                bad = [value for cell in row for value, places in numbers_in(cell)
                       if not (places == 0 and value <= 3) and not _supported(value, places, pool, derived, False)]
                if bad:
                    issues.append(Issue(" | ".join(row), f"table figure {bad[0]} is not in the cited evidence"))
                else:
                    rows.append(row)
            if rows:
                blocks.append({**block, "rows": rows, "evidence": ids})
        else:
            blocks.append(block)
    return Draft(blocks=blocks, follow_up_questions=draft.follow_up_questions, summary=summary), issues


def repair_prompt(issues: List[Issue]) -> str:
    lines = "\n".join(f"- \"{issue.claim[:160]}\": {issue.problem}" for issue in issues[:12])
    return ("Some claims in your JSON answer are not supported by the evidence:\n" + lines +
            "\nReturn the corrected JSON answer in the same format: cite only evidence that states each claim, "
            "copy figures exactly from the evidence or the KEEL calculation items, and turn anything the evidence "
            "does not establish into an \"unknown\" claim.")


# --- rendering ---------------------------------------------------------------

USED_AS = {FACT: "supports_fact", CALCULATION: "calculation", ESTIMATE: "supports_estimate",
           INFERENCE: "supports_analysis", RECOMMENDATION: "supports_recommendation",
           ASSUMPTION: "supports_assumption", UNKNOWN: "context", GENERAL: "context",
           "calculation_input": "calculation_input"}


def superscript(numbers: List[int]) -> str:
    return "˒".join(str(n).translate(_SUPERSCRIPT) for n in numbers)


def _answer_length(draft: Draft) -> int:
    texts = [c.text for b in draft.blocks if b["type"] == "paragraph" for c in b["claims"]]
    texts += [c.text for b in draft.blocks if b["type"] == "list" for item in b["items"] for c in item]
    texts += [cell for b in draft.blocks if b["type"] == "table" for row in b["rows"] for cell in row]
    return sum(len(t) for t in texts)


def _summary_claims(draft: Draft) -> List[Claim]:
    """What to show above a long answer: the model's own summary, else its first claims that state something
    (never a greeting or a lead-in), kept short. Empty when the answer is already short."""
    if _answer_length(draft) <= SUMMARY_MIN_ANSWER_CHARS:
        return []
    if draft.summary:
        return draft.summary
    picked: List[Claim] = []
    for block in draft.blocks:
        group = (block["claims"] if block["type"] == "paragraph" else
                 [c for item in block["items"] for c in item] if block["type"] == "list" else [])
        for claim in group:
            if claim.kind == GENERAL:
                continue
            if picked and sum(len(c.text) for c in picked) + len(claim.text) > SUMMARY_MIN_ANSWER_CHARS:
                return picked
            picked.append(claim)
            if len(picked) == SUMMARY_MAX_CLAIMS:
                return picked
    return picked


def render(draft: Draft, registry: ev.EvidenceRegistry, always: Iterable[str] = ()) -> dict:
    """Numbers the cited evidence in order of first use and returns the
    blocks for the interface, a plain-text answer with superscript markers,
    and the references. `always`: evidence that gets a reference even when
    no sentence cites it (a calculation the answer card links to)."""
    numbering: Dict[str, int] = {}
    used: Dict[str, Set[str]] = {}

    def refs(ids: List[str], kind: str) -> List[int]:
        out = []
        for evidence_id in ids:
            if evidence_id not in numbering:
                numbering[evidence_id] = len(numbering) + 1
            used.setdefault(evidence_id, set()).add(USED_AS.get(kind, "context"))
            out.append(numbering[evidence_id])
        return sorted(set(out))

    def claim_out(claim: Claim) -> dict:
        return {"text": claim.text, "kind": CALCULATION if claim.derived and claim.kind == FACT else claim.kind,
                "refs": refs(claim.evidence, claim.kind), "verified": claim.verified, "notes": claim.notes}

    summary = _summary_claims(draft)
    answer_summary = None
    if summary:
        # Numbered first, so the references the short answer cites are the lowest numbers.
        claims_out = [claim_out(c) for c in summary]
        answer_summary = {"text": " ".join(c["text"] for c in claims_out),
                          "claims": claims_out, "refs": sorted({n for c in claims_out for n in c["refs"]})}
    blocks, lines = [], []
    for block in draft.blocks:
        if block["type"] == "heading":
            blocks.append(block)
            lines.append(block["text"])
        elif block["type"] == "paragraph":
            claims = [claim_out(c) for c in block["claims"]]
            blocks.append({"type": "paragraph", "claims": claims})
            lines.append(" ".join(c["text"] + superscript(c["refs"]) for c in claims))
        elif block["type"] == "list":
            items = [[claim_out(c) for c in item] for item in block["items"]]
            blocks.append({"type": "list", "ordered": block["ordered"], "items": items})
            for index, item in enumerate(items, start=1):
                prefix = f"{index}. " if block["ordered"] else "- "
                lines.append(prefix + " ".join(c["text"] + superscript(c["refs"]) for c in item))
        elif block["type"] == "table":
            table_refs = refs(block.get("evidence") or [], FACT)
            blocks.append({**block, "refs": table_refs})
            lines.append("| " + " | ".join(block["columns"]) + " |")
            lines.append("|" + "---|" * len(block["columns"]))
            lines.extend("| " + " | ".join(row) + " |" for row in block["rows"])
            if table_refs:
                lines.append(superscript(table_refs))
    for evidence_id in always:
        if registry.get(evidence_id) is not None:
            refs([evidence_id], CALCULATION)
    # A cited calculation also lists, as references of their own, the sourced
    # inputs it was computed from (the user's figures, cited pages, records).
    input_refs: Dict[str, List[int]] = {}
    for evidence_id in [eid for eid in numbering]:
        item = registry.get(evidence_id)
        if item.kind != ev.CALCULATION:
            continue
        sourced, pending, seen = [], list((item.data or {}).get("input_evidence") or []), set()
        while pending:
            current = pending.pop(0)
            if current in seen or registry.get(current) is None:
                continue
            seen.add(current)
            source = registry.get(current)
            if source.kind == ev.CALCULATION:
                pending.extend((source.data or {}).get("input_evidence") or [])
            else:
                sourced.append(current)
        input_refs[evidence_id] = refs(sourced, "calculation_input") if sourced else []
    references = []
    for evidence_id, number in sorted(numbering.items(), key=lambda pair: pair[1]):
        reference = registry.get(evidence_id).reference(number, used[evidence_id])
        if evidence_id in input_refs:
            reference["input_refs"] = input_refs[evidence_id]
        references.append(reference)
    return {"blocks": blocks, "answer": "\n\n".join(line for line in lines if line), "references": references,
            "follow_up_questions": draft.follow_up_questions, "numbering": numbering,
            "summary": answer_summary}


def plain_text(answer: str) -> str:
    """The answer without reference markers (for conversation history)."""
    return re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹˒]+", "", answer or "")
