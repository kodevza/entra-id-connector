#!/usr/bin/env python3
# SPDX-License-Identifier: CDDL-1.1
"""Verify Entra reconciliation from a freshly started local OpenIDM instance."""

import json
import os
import time
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = os.environ.get("OPENIDM_URL", "http://localhost:8081/openidm")
HEADERS = {
    "X-OpenIDM-Username": os.environ.get("OPENIDM_USERNAME", "openidm-admin"),
    "X-OpenIDM-Password": os.environ["OPENIDM_PASSWORD"],
    "Content-Type": "application/json",
}
MAPPINGS = ("systemEntraGroup_managedEntraGroup", "systemEntraAccount_managedUser")


def request(path, method="GET"):
    body = b"{}" if method == "POST" else None
    with urlopen(Request(f"{BASE_URL}/{path}", body, HEADERS, method=method), timeout=30) as response:
        return json.load(response)


def reconcile(mapping):
    run_id = request(f"recon?_action=recon&mapping={mapping}", "POST")["_id"]
    for _ in range(90):
        result = request(f"recon/{run_id}")
        if result["state"] != "ACTIVE":
            return result["state"], result["statusSummary"]
        time.sleep(1)
    raise TimeoutError(f"{mapping}: {run_id}")


def query(path, query_filter, fields):
    params = {"_queryFilter": query_filter, "_fields": ",".join(fields), "_pageSize": 100}
    seen_cookies = set()
    while True:
        page = request(f"{path}?{urlencode(params)}")
        yield from page["result"]
        cookie = page.get("pagedResultsCookie")
        if not cookie:
            return
        if cookie in seen_cookies:
            raise RuntimeError(f"{path}: repeated pagination cookie")
        seen_cookies.add(cookie)
        params["_pagedResultsCookie"] = cookie


def verify_targets(mapping, source, tenant_field, source_id_field):
    tenant = next(p["default"] for p in mapping["properties"] if p["target"] == tenant_field)
    is_account = source_id_field == "entraObjectId"
    fields = ["_id", source_id_field, "displayName"]
    fields += ["accountStatus", "userName", "entraOidcSubject"] if is_account else ["collectedAt"]
    targets = {}
    for target in query(mapping["target"], f"{tenant_field} eq {json.dumps(tenant)}", fields):
        source_id = target[source_id_field]
        assert source_id not in targets, f"{mapping['name']}: duplicate managed record for {source_id}"
        targets[source_id] = target

    links = {}
    for link in query("repo/link", f"linkType eq {json.dumps(mapping['name'])}", ["firstId", "secondId"]):
        links.setdefault(link["firstId"], []).append(link["secondId"])

    for source_id, record in source.items():
        assert source_id in targets, f"{mapping['name']}: no managed record for {source_id}"
        target = targets[source_id]
        assert links.get(source_id) == [target["_id"]], f"{mapping['name']}: bad link for {source_id}"
        if is_account:
            display_name = record.get("displayName") or record.get("userPrincipalName") or source_id
            status = "active" if record["accountEnabled"] is True else "inactive"
            login = target.get("entraOidcSubject") or f"entra.{tenant}.{source_id}"
            assert target["displayName"] == display_name, f"{source_id}: incorrect display name"
            assert target["accountStatus"] == status, f"{source_id}: incorrect account status"
            assert target["userName"] == login, f"{source_id}: incorrect login"
        else:
            assert target.get("displayName") == record.get("displayName"), f"{source_id}: incorrect group name"
            assert datetime.fromisoformat(target["collectedAt"]).tzinfo is not None, f"{source_id}: timestamp has no timezone"
    return {source_id: target["_id"] for source_id, target in targets.items()}


def verify_mapping(mapping, tenant_field, source_id_field):
    source = {}
    fields = ["_id", "displayName"]
    if source_id_field == "entraObjectId":
        fields.extend(["userPrincipalName", "accountEnabled"])
    for row in query(mapping["source"], "true", fields):
        assert row["_id"] not in source, f"{mapping['name']}: duplicate connector record"
        source[row["_id"]] = row
    assert source, f"{mapping['name']}: connector returned no records"
    count_var = "EXPECTED_ENTRA_USERS" if source_id_field == "entraObjectId" else "EXPECTED_ENTRA_GROUPS"
    if count_var in os.environ:
        assert len(source) == int(os.environ[count_var]), f"{mapping['name']}: incomplete fixture import"

    snapshots = []
    for attempt in (1, 2):
        state, summary = reconcile(mapping["name"])
        print(mapping["name"], f"run {attempt}", state, summary, flush=True)
        assert state == "SUCCESS" and summary["FAILURE"] == 0, f"{mapping['name']}: {state}, {summary}"
        assert summary["SUCCESS"] >= len(source), f"{mapping['name']}: fewer successes than source records"
        snapshots.append(verify_targets(mapping, source, tenant_field, source_id_field))
    assert snapshots[0] == snapshots[1], f"{mapping['name']}: target IDs changed on repeat reconciliation"


if __name__ == "__main__":
    mappings = {m["name"]: m for m in request("config/sync")["mappings"]}
    verify_mapping(mappings[MAPPINGS[0]], "tenantId", "sourceId")
    verify_mapping(mappings[MAPPINGS[1]], "entraTenantId", "entraObjectId")
