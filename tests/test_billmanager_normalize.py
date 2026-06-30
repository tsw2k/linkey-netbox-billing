from linkey_billing.clients.billmanager import BillManagerClient, _as_list


def test_normalize_unwraps_dollar_scalars():
    raw = {"id": {"$": "123"}, "name": {"$": "vds-1"}}
    assert BillManagerClient._normalize(raw) == {"id": "123", "name": "vds-1"}


def test_normalize_handles_nested_lists():
    raw = {"elem": [{"id": {"$": "1"}}, {"id": {"$": "2"}}]}
    assert BillManagerClient._normalize(raw) == {"elem": [{"id": "1"}, {"id": "2"}]}


def test_unwrap_doc():
    assert BillManagerClient._unwrap_doc({"doc": {"a": 1}}) == {"a": 1}
    assert BillManagerClient._unwrap_doc({"a": 1}) == {"a": 1}


def test_as_list_normalizes_single_and_missing():
    assert _as_list(None) == []
    assert _as_list({"id": "1"}) == [{"id": "1"}]
    assert _as_list([{"id": "1"}]) == [{"id": "1"}]
