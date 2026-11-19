# Entra ownership workflow

In the OpenIDM Self Service dashboard, open **Processes** and select **Details**
for **Service principal — assign governance owner**. Select a service principal and nominate an owner
manually or paste OwnerLens evidence. The assigned owner opens the review from
the OpenIDM task list. Administrators can manage processes and task assignments
with the OpenIDM workflow views.

## Install

From the connector checkout, build the BAR, install the search endpoint, and
deploy the workflow and permissions:

```sh
(cd openidm/workflow-form && npm ci && npm test)
python3 openidm/install_owner_search.py
python3 openidm/install_permissions.py
```

If the standalone app or an earlier connector overlay is installed, remove it
after deploying the BAR:

```sh
python3 openidm/install_ownership_app.py --check
python3 openidm/install_ownership_app.py
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
