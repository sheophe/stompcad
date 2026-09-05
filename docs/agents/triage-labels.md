# Triage labels

Use these status values when a triage skill assigns a role to an issue:

| Skill role | Local status | Meaning |
| --- | --- | --- |
| `needs-triage` | `needs-triage` | A maintainer needs to assess the issue |
| `needs-info` | `needs-info` | More information is needed from the reporter |
| `ready-for-agent` | `ready-for-agent` | Specified and ready for an agent to implement |
| `ready-for-human` | `ready-for-human` | Needs human implementation |
| `wontfix` | `wontfix` | The proposed work will not be taken on |

These roles match `mattpocock/skills`. For example, a request to apply the
AFK-ready label means `ready-for-agent`.

Set the issue's `Status:` line near the top of its local Markdown file. Each
issue has one status; there is no label API to call. See the
[issue-tracker conventions](issue-tracker.md) for file paths.
