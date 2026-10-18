"""
KEEL - Vertical Playbook (general best-practice guidance per business
vertical, keyed to market_scraper.sector_detection's own vertical labels).

Real constraint, stated plainly: this is NOT tenant-specific data, and
NOT a fact pulled from anyone's records - it's general, industry-level
guidance a knowledgeable advisor would give a business of this kind,
applied alongside (never in place of) the tenant's own real numbers
(category_gap.py, cross_signal.py). SYSTEM_PROMPT's own "Two different
kinds of recommendation" paragraph exists specifically so the chatbot
never states one of these notes as if it were a confirmed fact about a
specific tenant - keep that distinction in mind if this dict is extended.

Pharmacies get the most explicit regulatory caution of any vertical here,
deliberately - PENDING_ACTIONS.md/RED_FLAGS.md's own "never fabricate
compliance data" discipline applies just as much to a recommendation as
to a claimed number: this platform has no real licensing/regulatory
database for any market, so the honest move is to flag that a licensing
check is needed before acting, never to imply this platform already knows
the answer.

Keyed by market_scraper.sector_detection.detect_vertical()'s own vertical
strings, plus "general_retail" as the same honest fallback that module
already uses when nothing scores a clear win.
"""
from typing import Dict

VERTICAL_PLAYBOOKS: Dict[str, Dict[str, str]] = {
    "pharmacy": {
        "add_priority_note": (
            "As a general rule for a pharmacy, prioritize essential and high-frequency, "
            "repeat-purchase categories (everyday OTC medicine, basic health supplies) over "
            "discretionary add-ons, and check with local pharmacy licensing/regulatory rules "
            "before adding any new medicine category - this platform doesn't know this "
            "market's specific licensing requirements, so that check has to happen separately."
        ),
        "remove_caution_note": (
            "For a pharmacy, weigh a real regulatory/insurance obligation to keep certain "
            "essential items in stock (even if they sell slowly) before treating low demand "
            "alone as a reason to drop something - that's a local-rules question this platform "
            "can't answer on its own."
        ),
    },
    "food_beverage": {
        "add_priority_note": (
            "As a general rule for a restaurant or cafe, weigh how perishable and prep-intensive "
            "a new item would be against the sales it might bring in - a slow-moving item that "
            "spoils is a bigger loss than a slow-moving item that doesn't."
        ),
        "remove_caution_note": (
            "For a restaurant or cafe, a low-selling menu item sometimes still earns its place by "
            "drawing in customers who order other things alongside it - worth checking whether it's "
            "usually ordered together with something popular before dropping it."
        ),
    },
    "hospitality": {
        "add_priority_note": (
            "As a general rule for a hotel or similar business, prioritize amenities/services that "
            "improve the guest experience directly (comfort, convenience, connectivity) over ones "
            "that mainly add cost without a clear guest-facing benefit, and expect demand for some "
            "additions to be seasonal rather than steady year-round."
        ),
        "remove_caution_note": (
            "For a hotel or similar business, a low-usage amenity can still matter for guest "
            "reviews and repeat bookings even if it isn't heavily used - worth checking guest "
            "feedback, not just usage numbers, before removing it."
        ),
    },
    "apparel_fashion": {
        "add_priority_note": (
            "As a general rule for apparel/fashion, new stock tends to be seasonal - weigh whether "
            "a category tracked competitors carry fits the coming season before committing to it."
        ),
        "remove_caution_note": (
            "For apparel/fashion, slow sales on an item can be a seasonal timing issue rather than "
            "a real lack of demand - worth checking whether it's currently in or out of season "
            "before deciding to drop it for good."
        ),
    },
    "electronics_hobbyist": {
        "add_priority_note": (
            "As a general rule for an electronics/components business, a new item is most useful "
            "when it's compatible with or complements what you already carry (the same project/"
            "component family), not just popular on its own."
        ),
        "remove_caution_note": (
            "For electronics/components, a slow-selling item that other, faster-selling items "
            "depend on (a common accessory or replacement part) can still be worth keeping in "
            "small quantity even at low turnover."
        ),
    },
    "home_furniture": {
        "add_priority_note": (
            "As a general rule for a furniture/home-goods business, weigh the real showroom space "
            "and delivery/logistics cost of a new item, not just whether competitors carry it - a "
            "bulky item that's slow to sell ties up more resources than a small one."
        ),
        "remove_caution_note": (
            "For furniture/home-goods, check current stock/storage cost against how slowly an item "
            "is actually moving before deciding to phase it out - a well-reviewed item can still be "
            "worth keeping at a lower stock level rather than dropping entirely."
        ),
    },
    "general_retail": {
        "add_priority_note": (
            "As a general rule, weigh how well a new category fits what you already sell and who "
            "already buys from you before adding it, not just that competitors carry it."
        ),
        "remove_caution_note": (
            "Low sales alone don't always mean an item should go - worth also checking sentiment "
            "and whether it brings in customers who then buy other things, before deciding."
        ),
    },
}


def get_playbook(vertical: str) -> Dict[str, str]:
    """Never raises for an unrecognized vertical - the same honest
    fallback-to-general_retail convention sector_detection.py's own
    build_industry_search_query() already uses."""
    return VERTICAL_PLAYBOOKS.get(vertical, VERTICAL_PLAYBOOKS["general_retail"])
