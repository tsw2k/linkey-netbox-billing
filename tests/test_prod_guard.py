import pytest

from billmanager.config import Settings
from billmanager.factory import ProdWriteGuardError, assert_write_target_allowed


def _settings(**over) -> Settings:
    base = dict(
        billmgr_url="x",
        billmgr_user="u",
        billmgr_password="p",
        netbox_url="https://netbox.prod.local",
        netbox_token="t",
        netbox_prod_markers="netbox.prod.local",
    )
    base.update(over)
    return Settings(**base)


def test_guard_blocks_prod_write():
    with pytest.raises(ProdWriteGuardError):
        assert_write_target_allowed(_settings(), allow_prod=False)


def test_guard_allows_with_flag():
    assert_write_target_allowed(_settings(), allow_prod=True)  # не бросает


def test_guard_allows_with_env_allow_prod():
    assert_write_target_allowed(_settings(allow_prod=True), allow_prod=False)


def test_guard_skips_on_dry_run():
    assert_write_target_allowed(_settings(dry_run=True), allow_prod=False)


def test_guard_allows_non_prod_url():
    s = _settings(netbox_url="http://127.0.0.1:8000")
    assert_write_target_allowed(s, allow_prod=False)  # маркер не совпал


def test_guard_no_markers_means_allowed():
    s = _settings(netbox_prod_markers="")
    assert_write_target_allowed(s, allow_prod=False)
