# Entra ownership workflow

In the OpenIDM Self Service dashboard, open **Processes** and select **Details**
for **Service principal — assign governance owner**. Select a service principal and nominate an owner
manually or paste OwnerLens evidence. The assigned owner opens the review from
the OpenIDM task list. Administrators can manage processes and task assignments
with the OpenIDM workflow views.

## Install

Follow the [workflow storage prerequisite](../docs/identity-and-ownership.md#workflow-storage-prerequisite)
for embedded H2 before deploying the workflow. From the connector checkout,
build the BAR and deploy the workflow and permissions:

```sh
(cd openidm/workflow-form && npm ci && npm test)
python3 tools/workshop/install_workflow_bar.py
python3 tools/workshop/install_permissions.py
```

The start form now queries `/openidm/managed/entraServicePrincipal` and
`/openidm/managed/user` directly (GET with `_queryFilter`, `_pageSize`, `_fields`).
Before retiring the old endpoint, verify both searches work using a **non-admin**
OIDC session. OpenIDM must authorize these reads and restrict which records and
attributes that role may read. `_fields` only limits the **request**; it is NOT
an authorization boundary. Do not grant `openidm-authorized` unrestricted access
to `managed/user` or `managed/entraServicePrincipal` as a workaround. If the
current authorization rules reject either read, this patch intentionally fails
closed (the UI shows the API error). A narrow server-side search service is
needed to preserve the former endpoint's least-privilege boundary.

Existing installations can remove the now-unused server lookup **after** the
new BAR is deployed and confirmed working, and after ensuring no older selectable
process definition still needs it:

```sh
python3 tools/workshop/remove_owner_search.py --check
python3 tools/workshop/remove_owner_search.py --apply
```

Removal makes a timestamped backup before deleting the config endpoint, deployed
script and the installer's exact access-rule block. Restart OpenIDM if its
`access.js` is cached. Do not delete the historical backup folders.

If the standalone app or an earlier connector overlay is installed, remove it
after deploying the BAR:

```sh
python3 tools/workshop/install_ownership_app.py --check
python3 tools/workshop/install_ownership_app.py
```

For the older OwnerLookup overlay, add
`--restore-from /opt/openidm/workflow-backups/owner-search-<timestamp>` to both
cleanup commands. Use the backup from before the first OwnerLookup installation.
Its numbered `StartProcessView.js` files should be the original Admin and Self
Service views. Reload both UIs after migration.

The cleanup records changes in
`/opt/openidm/workflow-backups/ownership-app-<timestamp>/manifest.json`. To roll
back the cleanup, restore each numbered backup to its original path and remove
entries whose backup is null.

Running instances remain attached to their original workflow definition. The
[form build and behavior guide](workflow-form/README.md) describes both forms.
