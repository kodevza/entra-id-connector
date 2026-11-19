# Ownership search endpoint

The Preact ownership application searches synchronized OpenIDM records using the
read-only `endpoint/ownerLookup` endpoint. It does not call Microsoft Graph during
searches.

```sh
python3 openidm/install_owner_search.py --check
python3 openidm/install_owner_search.py
node --test openidm/tests/owner-search.test.cjs
```

Defaults are `--url http://localhost:8081/openidm`, `--container openidm`,
`--home /opt/openidm`, and `--username openidm-admin`. The installer accepts
`OPENIDM_PASSWORD` or prompts for it. See [workflow UI installation](WORKFLOW_UI.md)
for installing the app that uses this endpoint.

Search starts after two characters and returns up to 20 matches. Service
principals can be found by display name, Entra Object ID or application/client
ID. After a principal is selected, the owner search includes only active users
in the same tenant and matches display name, first/last name, login, email or
Entra Object ID. Changing the principal clears the owner selection.

The endpoint returns only Entra Object IDs and display labels. It uses fixed
collections and fields and escapes query literals. The default permitted roles
are `openidm-authorized` and `openidm-admin`. If your deployment restricts who can
start requests, align the endpoint access rule with those roles.

The installer backs up the prior endpoint configuration, script, and access
rules under `/opt/openidm/workflow-backups/owner-search-*`.
