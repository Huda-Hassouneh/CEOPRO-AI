"""
What each team role may see through the assistant.

Row-level security already keeps every company's data apart; this module
decides, inside one company, which kinds of records a signed-in member may
have the assistant read, quote or cite. Every assistant data path asks
`allows()` before it reads (structured facts, analysis tools, document
passages, generated summaries) and the reference panel only ever shows
evidence that passed this check.

Roles come from tenant_users.role_key and are read fresh on every
question, so a role change or a removal takes effect immediately. An
unknown role, a removed member or a failed lookup gets the narrowest
access (public product help and public research only).
"""
from dataclasses import dataclass
from typing import FrozenSet, Optional

SALES = "sales"              # revenue, invoices, units sold
COSTS = "costs"              # cost prices, margins, profit
CATALOG = "catalog"          # products, selling prices
INVENTORY = "inventory"      # stock levels and restock checks
FORECASTS = "forecasts"      # demand forecasts
MARKETING = "marketing"      # campaigns
COMPETITORS = "competitors"  # tracked competitors and their prices
REVIEWS = "reviews"          # customer reviews and sentiment
DOCUMENTS = "documents"      # documents the company uploaded

ALL_CAPABILITIES: FrozenSet[str] = frozenset(
    {SALES, COSTS, CATALOG, INVENTORY, FORECASTS, MARKETING, COMPETITORS, REVIEWS, DOCUMENTS}
)

ROLE_CAPABILITIES = {
    "owner": ALL_CAPABILITIES,
    "admin": ALL_CAPABILITIES,
    "manager": ALL_CAPABILITIES,
    "accountant": frozenset({SALES, COSTS, CATALOG, INVENTORY, FORECASTS, DOCUMENTS}),
    "staff": frozenset({CATALOG, INVENTORY}),
}

# Generated summary documents (structured_summaries.py) hold the same data
# as the live tools, so they need the same capability; help documents are
# the same for everyone.
SUMMARY_CAPABILITIES = {
    "sales_history": frozenset({SALES}),
    "competitor_landscape": frozenset({COMPETITORS}),
    "sentiment_trends": frozenset({REVIEWS}),
    "market_pricing": frozenset({COMPETITORS, CATALOG}),
    "demand_forecast": frozenset({FORECASTS}),
    "strategic_insights": frozenset({SALES, COSTS}),
    "platform_help": frozenset(),
    "pos_erp_systems": frozenset(),
    "troubleshooting_help": frozenset(),
}


@dataclass(frozen=True)
class Access:
    role: Optional[str]
    capabilities: FrozenSet[str]

    def allows(self, *needed: str) -> bool:
        return all(capability in self.capabilities for capability in needed)

    def missing(self, *needed: str) -> FrozenSet[str]:
        return frozenset(capability for capability in needed if capability not in self.capabilities)


NO_ACCESS = Access(role=None, capabilities=frozenset())
FULL_ACCESS = Access(role="owner", capabilities=ALL_CAPABILITIES)


def for_role(role: Optional[str]) -> Access:
    return Access(role=role, capabilities=ROLE_CAPABILITIES.get(role or "", frozenset()))


def load_access(conn, tenant_id: str, user_id: Optional[str]) -> Access:
    """The member's current role in this company (RLS-scoped connection)."""
    if conn is None or not user_id:
        return NO_ACCESS
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT role_key FROM tenant_users WHERE tenant_id = %s AND user_id = %s AND removed_at IS NULL;",
                (tenant_id, user_id),
            )
            row = cursor.fetchone()
    except Exception:  # noqa: BLE001 - a failed lookup must never widen access
        return NO_ACCESS
    return for_role(row[0]) if row else NO_ACCESS


def document_capabilities(storage_path: Optional[str]) -> FrozenSet[str]:
    """Capabilities needed to read a document, from where it is stored."""
    path = storage_path or ""
    if path.startswith("_generated/"):
        slot = path[len("_generated/"):].rsplit(".", 1)[0]
        # An unrecognised generated document is treated as company data.
        return SUMMARY_CAPABILITIES.get(slot, frozenset({SALES, COSTS}))
    return frozenset({DOCUMENTS})
