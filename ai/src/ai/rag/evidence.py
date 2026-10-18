"""
The evidence one assistant answer may draw on, and the references shown
for it.

Every fact the assistant is given (a company record, a document passage,
a page read during research, a calculation step, a value the user typed)
becomes one `Evidence` item with a stable id ("E1", "E2", ...) for this
question only. The model cites those ids; citations.py checks each
citation against the item's own text before anything reaches the user;
the items actually cited become the numbered references (1, 2, 3 ... in
order of first use) that the reference panel shows.

An item never claims more than its source says: `status` records whether
the text was observed as published, extracted from a page, calculated by
KEEL, or provided by the user, and `limitations` carries what is known to
be missing or uncertain (an old observation, a page with no date, a
summary rather than the record itself).
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, FrozenSet, Iterable, List, Optional

# kind: what the item is
COMPANY_RECORD = "company_record"        # a live query of the company's own data
COMPANY_SUMMARY = "company_summary"      # a generated summary document
COMPANY_DOCUMENT = "company_document"    # a passage from a document the company uploaded
PRODUCT_GUIDE = "product_guide"          # how KEEL itself works
WEB_PAGE = "web_page"                    # a public page read during research
CALCULATION = "calculation"              # a step computed by KEEL
USER_INPUT = "user_input"                # a value stated by the user in this conversation

# credibility: how much weight the source carries
OFFICIAL = "official"        # government, regulator, customs or tax authority, standards body
PRIMARY = "primary"          # the business, manufacturer or publisher the fact is about
COMPANY = "company"          # the company's own records
SECONDARY = "secondary"      # news, directories, aggregators, commentary
USER = "user"
CALCULATED = "calculated"

# status: how the text was obtained
OBSERVED = "observed"
EXTRACTED = "extracted"
CALCULATED_STATUS = "calculated"
USER_PROVIDED = "user_provided"
SUMMARISED = "summarised"

_SOURCE_TAG = re.compile(r"\s*\(source:[^)]*\)", re.IGNORECASE)
_LINK = re.compile(r"\bLink:\s*(https?://\S+)")
_MAX_EXCERPT = 1200


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


# Arabic titles for the company-fact groups (structured_context.py and the
# analysis tools write their headers in English).
_AR_TITLES = (
    (re.compile(r"^Sales in the last (\d+) days"), r"المبيعات في آخر \1 يوماً"),
    (re.compile(r"^Top products by revenue in the last (\d+) days"), r"أعلى المنتجات إيراداً في آخر \1 يوماً"),
    (re.compile(r"^Gross margin analysis for the trailing (\d+) days"), r"تحليل هامش الربح الإجمالي لآخر \1 يوماً"),
    (re.compile(r"^Current overall sentiment score"), "مؤشر رضا الزبائن العام"),
    (re.compile(r"^Current tracked competitor count by tier"), "عدد المنافسين المتابَعين حسب الفئة"),
    (re.compile(r"^Your actual tracked competitors by name"), "المنافسون المتابَعون"),
    (re.compile(r"^Market scan"), "مسح السوق"),
    (re.compile(r"^Largest price gaps"), "أكبر فروق الأسعار مع المنافسين"),
    (re.compile(r"^Current demand forecasts"), "أحدث توقعات الطلب"),
    (re.compile(r"^Proactive insights"), "ملاحظات استباقية"),
    (re.compile(r"^Recently observed competitor activity"), "نشاط المنافسين المرصود مؤخراً"),
    (re.compile(r"^Top-selling products by gross profit"), "المنتجات الأعلى ربحاً"),
    (re.compile(r"^Products at or below their reorder level"), "منتجات وصلت حد إعادة الطلب"),
    (re.compile(r"^Inventory"), "المخزون"),
    (re.compile(r"^Restock check"), "فحص إعادة التخزين"),
    (re.compile(r"^Competitor comparison"), "مقارنة المنافسين"),
    (re.compile(r"^Product sales trends"), "اتجاهات مبيعات المنتجات"),
    (re.compile(r"^Root-cause signals"), "مؤشرات أسباب تغيّر الإيراد أو الربح"),
    (re.compile(r"^(Recent )?[Mm]arketing campaigns"), "الحملات التسويقية"),
    (re.compile(r"^Demand forecast summary"), "ملخص توقعات الطلب"),
    (re.compile(r"^Tracked competitors|^Competitors"), "المنافسون المتابَعون"),
    (re.compile(r"^KEEL product guide|^How to do this in KEEL"), "دليل استخدام KEEL"),
)


def localized_title(title: str, language: str) -> str:
    if language != "ar":
        return title
    for pattern, arabic in _AR_TITLES:
        match = pattern.match(title or "")
        if match:
            # Keep the number a pattern captured (the period length).
            return match.expand(arabic) if match.groups() else arabic
    return title


def _link(text: str) -> Optional[str]:
    """The public page a company fact points at ("... Link: https://...")."""
    match = _LINK.search(text or "")
    return match.group(1).rstrip(".,;") if match else None


def clean_title(text: str) -> str:
    """A section header without the internal source tag or trailing colon."""
    text = _SOURCE_TAG.sub("", text or "").strip()
    text = re.sub(r"\s*-\s*(only mention|cite these|each line|always include).*$", "", text, flags=re.IGNORECASE)
    return text.rstrip(":.- ").strip()


@dataclass
class Evidence:
    id: str
    kind: str
    title: str
    excerpt: str
    credibility: str
    status: str
    organisation: Optional[str] = None
    url: Optional[str] = None
    route: Optional[str] = None
    locator: Optional[str] = None
    published_at: Optional[str] = None
    effective_at: Optional[str] = None
    observed_at: Optional[str] = None
    retrieved_at: Optional[str] = None
    jurisdiction: Optional[str] = None
    applies_to: Optional[str] = None
    limitations: List[str] = field(default_factory=list)
    capabilities: FrozenSet[str] = frozenset()
    data: Optional[dict] = None

    def prompt_block(self, max_chars: Optional[int] = None) -> str:
        """How the item is shown to the model: id, provenance, then the text
        (shortened to max_chars when the prompt has to be compact)."""
        facts = [self.kind.replace("_", " "), self.title]
        for label, value in (("published", self.published_at), ("effective", self.effective_at),
                             ("observed", self.observed_at), ("retrieved", self.retrieved_at)):
            if value:
                facts.append(f"{label} {value[:10]}")
        if self.jurisdiction:
            facts.append(f"jurisdiction {self.jurisdiction}")
        if self.organisation:
            facts.append(self.organisation)
        if self.url:
            facts.append(self.url)
        if self.limitations:
            facts.append("limits: " + "; ".join(self.limitations))
        text = self.excerpt if not max_chars or len(self.excerpt) <= max_chars else self.excerpt[:max_chars] + " …"
        return f"[{self.id}] " + " | ".join(facts) + f"\n{text}"

    def reference(self, number: int, used_as: Iterable[str]) -> dict:
        return {
            "n": number, "evidence_id": self.id, "kind": self.kind, "title": self.title,
            "organisation": self.organisation, "url": self.url, "route": self.route, "locator": self.locator,
            "excerpt": self.excerpt, "published_at": self.published_at, "effective_at": self.effective_at,
            "observed_at": self.observed_at, "retrieved_at": self.retrieved_at,
            "jurisdiction": self.jurisdiction, "applies_to": self.applies_to,
            "credibility": self.credibility, "status": self.status, "limitations": list(self.limitations),
            "used_as": sorted(set(used_as)),
            **({"calculation": self.data} if self.kind == CALCULATION and self.data else {}),
        }


class EvidenceRegistry:
    """The evidence gathered for one question, in the order it was added."""

    def __init__(self):
        self._items: Dict[str, Evidence] = {}

    def add(self, kind: str, title: str, excerpt: str, credibility: str, status: str, **details) -> Evidence:
        excerpt = (excerpt or "").strip()
        if len(excerpt) > _MAX_EXCERPT:
            excerpt = excerpt[:_MAX_EXCERPT].rsplit(" ", 1)[0] + " …"
        for key in ("published_at", "effective_at", "observed_at", "retrieved_at"):
            if key in details:
                details[key] = _iso(details[key])
        # The same text from the same place is one piece of evidence, not two.
        for existing in self._items.values():
            if existing.kind == kind and existing.excerpt == excerpt and existing.url == details.get("url") \
                    and existing.title == (title or "").strip():
                return existing
        item = Evidence(id=f"E{len(self._items) + 1}", kind=kind, title=(title or "").strip() or kind,
                        excerpt=excerpt, credibility=credibility, status=status, **details)
        self._items[item.id] = item
        return item

    def get(self, evidence_id: str) -> Optional[Evidence]:
        return self._items.get(evidence_id)

    def items(self) -> List[Evidence]:
        return list(self._items.values())

    def __len__(self) -> int:
        return len(self._items)

    def localize_titles(self, language: str) -> None:
        """Company-fact titles in the user's language (excerpts stay as recorded)."""
        for item in self._items.values():
            if item.kind in (COMPANY_RECORD, PRODUCT_GUIDE):
                item.title = localized_title(item.title, language)

    def prompt_text(self) -> str:
        return "\n\n".join(item.prompt_block() for item in self._items.values())

    def add_fact_lines(self, lines: List[str], *, route: Optional[str], capabilities: FrozenSet[str],
                       observed_at=None, title: Optional[str] = None, kind: str = COMPANY_RECORD,
                       credibility: str = COMPANY) -> List[Evidence]:
        """Company facts written as a header line followed by "- " detail
        lines (the format every structured-facts builder uses): each detail
        line is one item titled by the header above it; a header with no
        detail lines is an item of its own."""
        added: List[Evidence] = []
        header = title
        pending_header: Optional[str] = None

        def standalone(line: str) -> Evidence:
            text = _SOURCE_TAG.sub("", line).strip()
            return self.add(kind, title or clean_title(text.split(":", 1)[0]), text, credibility, OBSERVED,
                            route=route, capabilities=capabilities, observed_at=observed_at, url=_link(text))

        for raw in lines:
            line = (raw or "").strip()
            if not line:
                continue
            if line.startswith("- "):
                body = _SOURCE_TAG.sub("", line[2:]).strip()
                added.append(self.add(kind, clean_title(header or "Company data"), body, credibility,
                                      OBSERVED, route=route, capabilities=capabilities, observed_at=observed_at,
                                      url=_link(body)))
                pending_header = None
                continue
            if pending_header:
                added.append(standalone(pending_header))
            header = line
            pending_header = line
        if pending_header:
            added.append(standalone(pending_header))
        return added
