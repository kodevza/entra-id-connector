# SPDX-License-Identifier: CDDL-1.1
"""Verify creation and updates through the OpenIDM reconciliation API."""
from datetime import datetime
import json
from urllib.request import Request, urlopen

from live_reconciliation import query, reconcile
from mock_entra import APP_ID, BASE, PRINCIPAL, RESOURCE, ROLE, TENANT

MAPPING = "systemEntraServicePrincipal_managedEntraServicePrincipal"


def snapshot(name, enabled, permissions):
    state, summary = reconcile(MAPPING)
    print(MAPPING, state, summary, flush=True)
    assert state == "SUCCESS" and summary["FAILURE"] == 0, summary
    rows = list(query("managed/entraServicePrincipal", f'tenantId eq "{TENANT}"',
                      ["_id", "sourceId", "displayName", "appId", "accountEnabled", "grantedAccessJson"]))
    targets = {row["sourceId"]: row for row in rows}
    assert len(rows) == 2 and targets.keys() == {PRINCIPAL, RESOURCE}, rows
    principal = targets[PRINCIPAL]
    assert principal["displayName"] == name, principal
    assert principal["appId"] == APP_ID and principal["accountEnabled"] is enabled, principal
    grants = json.loads(principal["grantedAccessJson"])
    assert datetime.fromisoformat(grants["collectedAt"]).tzinfo is not None, grants
    assert grants["permissions"] == permissions, grants
    ids = {source: row["_id"] for source, row in targets.items()}
    links = list(query("repo/link", f'linkType eq "{MAPPING}"', ["firstId", "secondId"]))
    assert sorted((link["firstId"], link["secondId"]) for link in links) == sorted(ids.items()), links
    return ids


if __name__ == "__main__":
    initial = snapshot("Fixture application", True, [{
        "kind": "application", "grantId": "fixture-grant", "resourceId": RESOURCE,
        "resourceName": "Fixture API", "resourceAppId": None, "permissionId": ROLE, "permission": "Inventory.Read",
        "displayName": "", "description": "Read inventory",
    }])
    with urlopen(Request(f"{BASE}/fixture/update-principal", method="POST"), timeout=10) as response:
        assert response.status == 200
    assert snapshot("Updated application", False, []) == initial
