"""The port exists so the domain does not depend on ESI.

This test is a shape check: a stub that satisfies the protocol proves the
interface is implementable without importing anything from infrastructure.
"""

from contracts.domain.gateway import (
    ContractSourceError,
    ContractSourceGateway,
    ScopeRejected,
)


class StubGateway:
    def fetch_contracts(self, *, character_id, access_token):
        return ()

    def fetch_items(self, *, character_id, contract_id, access_token):
        return ()

    def resolve_names(self, ids):
        return {}


def test_a_plain_object_satisfies_the_protocol():
    assert isinstance(StubGateway(), ContractSourceGateway)


def test_scope_rejection_is_a_contract_source_error():
    """Callers that only catch the base class must still catch a 403."""
    assert issubclass(ScopeRejected, ContractSourceError)


def test_the_port_does_not_import_infrastructure():
    """The whole point of the layering. A domain module importing requests or
    django breaks the promise that verification tests need no environment."""
    import contracts.domain.gateway as module

    with open(module.__file__) as handle:
        source = handle.read()

    assert "import requests" not in source
    assert "django" not in source
