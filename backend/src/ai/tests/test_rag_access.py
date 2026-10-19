"""Which records each team role may have the assistant read (rag/access.py)."""
from src.ai.rag import access as acl


def test_role_capabilities():
    assert acl.for_role("owner").capabilities == acl.ALL_CAPABILITIES
    assert acl.for_role("manager").allows(acl.SALES, acl.COSTS, acl.DOCUMENTS)
    accountant = acl.for_role("accountant")
    assert accountant.allows(acl.SALES, acl.COSTS) and not accountant.allows(acl.MARKETING)
    staff = acl.for_role("staff")
    assert staff.allows(acl.CATALOG, acl.INVENTORY)
    assert not staff.allows(acl.SALES) and not staff.allows(acl.COSTS) and not staff.allows(acl.DOCUMENTS)
    assert staff.missing(acl.SALES, acl.CATALOG) == frozenset({acl.SALES})


def test_unknown_roles_and_failed_lookups_get_nothing():
    assert acl.for_role("intern").capabilities == frozenset()
    assert acl.for_role(None).capabilities == frozenset()
    assert acl.load_access(None, "t", "u") == acl.NO_ACCESS

    class Broken:
        def cursor(self):
            raise RuntimeError("database down")

    assert acl.load_access(Broken(), "t", "u") == acl.NO_ACCESS


def test_documents_need_the_capability_of_the_data_they_hold():
    assert acl.document_capabilities("uploads/contract.pdf") == frozenset({acl.DOCUMENTS})
    assert acl.document_capabilities("_generated/sales_history.txt") == frozenset({acl.SALES})
    assert acl.document_capabilities("_generated/platform_help.txt") == frozenset()
    # An unrecognised generated summary is treated as company financial data.
    assert acl.document_capabilities("_generated/new_slot.txt") == frozenset({acl.SALES, acl.COSTS})
