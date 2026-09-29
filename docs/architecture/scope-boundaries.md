# Product scope boundaries

This table is the navigation, authorization, and persistence source of truth. A feature's placement must match the resource that owns its data; selecting a Team must not silently change workspace- or user-owned data.

| Feature | Owner / scope | Navigation | Notes |
| --- | --- | --- | --- |
| Profile, security, connected accounts | User | Settings → Personal | Shared across every workspace. Authentication methods are owned by the Auth Service. |
| Notification preferences | User | Settings → Personal | Delivery preferences belong to the recipient, not a Team. |
| My Issues | Workspace + current user | Workspace navigation | Aggregates assignments across accessible Teams in the selected workspace. |
| Inbox | Workspace + current user | Workspace navigation | Aggregates authorized notifications across all Teams in the selected workspace. |
| Saved Views | Workspace collection | Workspace navigation | Each view stores a `team_id` because its issue query is Team-scoped; visibility can be private, Team, or workspace. |
| Workspace profile, members, invitations, domain policy | Workspace | Settings → Workspace | Owner/admin writes; membership reads are workspace-wide. |
| GitHub integration | Workspace | Settings → Workspace → Applications | PR titles are matched against every Team issue prefix in the workspace; no Team or project mapping exists. |
| Overview, Summary, Issues, Cycles, Projects | Team | Expanded Team sub-navigation | These resources and dashboards use an explicit `team_id`. |
| Team members | Team | Team → Members | Team leads and workspace admins manage access for the selected Team; candidates must already be workspace members. |
| Workflow states and labels | Team | Team configuration context | They define one Team's issue workflow and taxonomy. |
| Cycle board | Team + Cycle | Team → Cycles | A Cycle belongs to exactly one Team. Its operational dashboard is a sprint/Kanban board grouped by the Team's workflow states; it is separate from Team Summary analytics. |
| Cycle schedule | Team | Team → Cycles → Schedule | Team leads and workspace admins configure repeating duration, number of future cycles, and unfinished-issue rollover. |

The Business API continues to authorize every request independently. Navigation placement is not an access-control mechanism.
