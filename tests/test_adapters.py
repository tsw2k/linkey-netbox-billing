from linkey_billing.models import netbox_status_for, slugify
from linkey_billing.sync.adapters import client_from_bm, service_from_bm


def test_client_from_bm_collects_alternate_keys():
    c = client_from_bm({"id": "42", "realname": "ООО Линки"})
    assert c.bm_id == "42"
    assert c.name == "ООО Линки"
    assert c.slug == slugify("ООО Линки-42")


def test_service_from_bm_parses_ips_and_specs():
    s = service_from_bm(
        {
            "id": "7",
            "name": "vds-prod",
            "client": "42",
            "status": "2",
            "cpu": "4",
            "mem": "8192",
            "disk": "100",
            "ip": "203.0.113.5, 203.0.113.6",
            "vlan": "150",
        }
    )
    assert s.bm_id == "7"
    assert s.client_bm_id == "42"
    assert s.vcpus == 4 and s.memory_mb == 8192 and s.disk_gb == 100
    assert s.ip_addresses == ["203.0.113.5", "203.0.113.6"]
    assert s.vlan_id == 150


def test_status_mapping():
    assert netbox_status_for("2") == "active"
    assert netbox_status_for("3") == "offline"
    assert netbox_status_for("999") == "active"  # дефолт
