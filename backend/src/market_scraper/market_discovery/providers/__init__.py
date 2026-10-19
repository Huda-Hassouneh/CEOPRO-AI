"""Discovery sources. Each module exposes NAME, available() -> (bool, reason)
and search(query) -> ProviderResult, and never invents a business: no key,
no network or no match all come back as an empty, explained result."""
