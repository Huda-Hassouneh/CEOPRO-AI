"""Shared text-search SQL: one definition of "matches the search box" for
products everywhere (Products list, the top-bar search)."""


def like_pattern(term: str) -> str:
    """%term% with LIKE wildcards in the user's term escaped."""
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def any_text(column: str) -> str:
    """SQL true when any language of a localized JSONB column (or a plain
    JSON string value) contains the %s pattern."""
    return (
        "EXISTS (SELECT 1 FROM jsonb_each_text(CASE WHEN jsonb_typeof({c}) = 'object' THEN {c} "
        "ELSE jsonb_build_object('v', {c} #>> '{{}}') END) v WHERE v.value ILIKE %s)"
    ).format(c=column)


def product_match(alias: str = "p") -> str:
    """Name in any language, brand or category - three %s placeholders."""
    return f"({any_text(alias + '.product_name')} OR {any_text(alias + '.brand')} OR {any_text(alias + '.category')})"
