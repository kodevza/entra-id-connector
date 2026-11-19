# Entra ownership workflow forms

The Activiti BAR contains Preact form fragments for the OpenIDM Start Process
and task views. The start form uses the selected process definition and the
existing OpenIDM session.

## Build and test

Requires Node.js 22+ and Python 3:

```sh
cd openidm/workflow-form
npm ci
npm test
```

`npm run build` produces:

- `../../target/workflow/servicePrincipalOwner.bar` — deployment artifact.
- `../../target/workflow/servicePrincipalOwner.html` — compiled review form for inspection.
- `../../target/workflow/servicePrincipalOwnerStart.html` — compiled start form for inspection.

The archive contains:

```text
servicePrincipalOwner.bpmn20.xml
forms/servicePrincipalOwner.html
forms/servicePrincipalOwnerStart.html
licenses/PREACT.txt
licenses/CDDL-1.1.txt
```

The HTML includes Preact, scoped CSS and the application code. There are no
runtime CDN imports, external assets, Node.js server or browser Graph calls.
Dependencies are pinned in `package-lock.json`. Archive entries have fixed
timestamps, making builds reproducible. Rebuild after changing BPMN or form code;
the installer rejects a BAR whose BPMN differs from the current source.

## Install

See [workflow UI installation](../WORKFLOW_UI.md) for deployment and migration.
The BAR installer verifies that the latest process and task definitions serve their forms from
the archive. Keep legacy deployment files for running and historical workflow
instances. New requests use the latest definition.

## Review behavior

The form shows subject and nominee details, collection time, permission names,
API/resource names, descriptions, delegated consent/user IDs and directory scopes.
Search and type filters apply to the permission table. Empty, missing and invalid
snapshots have distinct messages. The app submits the decision and, for forwarding, the selected candidate's Entra Object ID.
Manual nominations retain their explicit **Reject and block service principal**
decision.

## OwnerLens Lite review

Export an un-anonymized OwnerLens Lite report with
`Invoke-OwnerLensLite -EnterpriseApplication <id> -OutputPath ./report.json`.
From the Entra connector repository, generate an OpenIDM start request:

```sh
python3 openidm/ownerlens_payload.py report.json \
  --definition-id "$WORKFLOW_DEFINITION_ID" > owner-review.json
```

Use the latest `servicePrincipalOwner` definition ID from
`GET /openidm/workflow/processdefinition?_queryId=filtered-query`. Submit the
generated body with an authorized `POST /openidm/workflow/processinstance?_action=create`.
The body contains the enterprise application's Entra Object ID, a reason, and
the `ownerEvidenceJson` string. The start form also accepts that string in
**OwnerLens evidence JSON** with the service principal and reason.

The **Request** tab shows the service principal, granted permissions and ranked
candidates. The **Evidence** tab shows the original OwnerLens signals in a
searchable table with separate subscription ID and role columns and filters.
The decision controls are visible on both tabs. The workflow matches candidate Entra Object IDs or exact
UPNs to active synchronized users in the service principal's tenant. Other
evidence remains visible as context. Candidates are ordered by their strongest
confidence band (HIGH, MED, LOW), using their report order to break ties.
Each user appears once in the assignment list, even with multiple evidence rows.

The first candidate gets the review task. They can accept, decline, or forward
to an available candidate in the table. Declining always resumes the original
ranking and skips anyone who already reviewed the request or is no longer
eligible. Acceptance assigns the acting reviewer as the OpenIDM governance
owner. After the final decline the request is marked `exhausted`. Declining an
OwnerLens review leaves the service principal enabled and preserves its current
ownership. History records each reviewer, decision, timestamp and next reviewer.

The BPMN copies `grantedAccessJson` into task variables while retaining the
protected authoritative request snapshot. Escaped Handlebars textareas carry data
into Preact; directory strings never become executable JavaScript or HTML. The
backend continues to enforce the nominee, tenant, account status, pending request
and concurrent ownership rules. The backend resolves forwarding choices against the stored candidate list and review history.

## Integration test coverage

`npm test` checks TypeScript, builds the BAR, and exercises both archived
forms in jsdom. Start tests cover tenant-scoped lookup, manual and OwnerLens
payloads, and retry after a failed start. Review tests cover escaped variables,
permission filters, decisions, and forwarding.
