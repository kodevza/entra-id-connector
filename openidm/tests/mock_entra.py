# SPDX-License-Identifier: CDDL-1.1
"""Loopback-only OAuth and Microsoft Graph fixtures for the OpenIDM test."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

BASE = "http://127.0.0.1:8765"
TENANT = "10000000-0000-4000-8000-000000000001"
CLIENT = "10000000-0000-4000-8000-000000000002"
SECRET = "openidm-test-secret"
TOKEN = "openidm-test-token"
GROUPS = [
    {"id": f"20000000-0000-4000-8000-{i:012d}", "displayName": f"Offline group {i}"}
    for i in range(1, 12)
]
USERS = [
    {
        "id": f"30000000-0000-4000-8000-{i:012d}",
        "displayName": f"Offline user {i}",
        "userPrincipalName": f"user{i}@example.invalid",
        "accountEnabled": i % 2 == 1,
    }
    for i in range(1, 5)
]


PRINCIPAL = "40000000-0000-4000-8000-000000000001"
RESOURCE = "40000000-0000-4000-8000-000000000002"
ROLE = "50000000-0000-4000-8000-000000000001"
APP_ID = "60000000-0000-4000-8000-000000000001"


class Handler(BaseHTTPRequestHandler):
    updated = False

    def respond(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path == "/fixture/update-principal":
            type(self).updated = True
            self.respond(200, {})
            return
        form = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
        if self.path != "/token" or any(form.get(k) != [v] for k, v in {
            "client_id": CLIENT, "client_secret": SECRET,
            "grant_type": "client_credentials", "scope": "https://graph.microsoft.com/.default",
        }.items()):
            self.respond(400, {"error": "unexpected token request"})
            return
        self.respond(200, {"access_token": TOKEN, "expires_in": 3600})

    def do_GET(self):
        url = urlsplit(self.path)
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self.respond(401, {"error": "fixture bearer token required"})
            return
        updated = self.updated
        records = {
            "/graph/groups": GROUPS,
            "/graph/users": USERS,
            "/graph/servicePrincipals": [
                {"id": PRINCIPAL, "appId": APP_ID, "accountEnabled": not updated,
                 "displayName": "Updated application" if updated else "Fixture application",
                 "servicePrincipalType": "Application"},
                {"id": RESOURCE, "displayName": "Fixture API",
                 "appRoles": [{"id": ROLE, "value": "Inventory.Read", "description": "Read inventory"}]},
            ],
            f"/graph/servicePrincipals/{PRINCIPAL}/appRoleAssignments": [] if updated else [
                {"id": "fixture-grant", "resourceId": RESOURCE, "appRoleId": ROLE},
            ],
            f"/graph/servicePrincipals/{RESOURCE}/appRoleAssignments": [],
            "/graph/oauth2PermissionGrants": [],
            "/graph/roleManagement/directory/roleAssignments": [],
            "/graph/roleManagement/directory/roleDefinitions": [],
        }.get(url.path)
        if records is None:
            self.respond(404, {"error": "unknown fixture route"})
            return
        if parse_qs(url.query).get("page") == ["2"]:
            self.respond(200, {"value": records[2:]})
        else:
            self.respond(200, {
                "value": records[:2],
                "@odata.nextLink": f"{BASE}{url.path}?page=2",
            })


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
