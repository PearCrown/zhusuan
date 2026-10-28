# Project execution rules

This is the independent account module for 《铸算·华夏纪》. The user is a beginner and wants short reports of completed results, limitations, and next fixes. Do not delegate or create other chats.

## Current task boundary

Groups 1–8 passed locally; GitHub contains groups 1–6. Group 8 provides password change and maintainer-assisted one-use recovery with reauthentication, hashed credentials bound to revision/auth state, audit and full old-session invalidation. No real password was changed or real maintainer provisioned. Do not start game/contacts/OTP work or publish before handoff. Preserve data and apply mandatory autonomous review.

## Persistent architecture and business decisions

- Django 5.2 LTS pinned to a supported patch; stable Python 3.12; PostgreSQL for development and database tests. No silent SQLite fallback.
- Configure a custom AbstractUser-based user model with fixed userId before the first application migration. The temporary manage.py migration guard must only be removed once this is configured in group 2. Never erase migrations or reset data to bypass a problem.
- Reuse Django password and server-side session mechanisms. Do not introduce JWT/localStorage identity or duplicate credential/session systems.
- Students, teachers, and restricted maintainers are separate permissions. Teachers can still play; teacher status does not imply admin access. Maintainers do not automatically have score-query permissions.
- Students can be unassigned or belong to one class; teachers may manage several explicitly authorized classes. Check roles, ownership, active status, and class scopes on the server for every relevant request, including CSV.
- Identity comes from the session, never trusted client userId/role/classId. Revocation/disablement must affect the next relevant request.
- Group 4 revokes a disabled session when presented. Group 7 maintenance now also increments session_revision in the framework auth hash to permanently invalidate all previous tokens, including never-presented tokens across disable/re-enable. Direct SQL/shell changes bypass this service and do not automatically get the same audit/revocation guarantee.
- Password change/reset invalidates all old sessions including the current session. Reset credentials are short-lived and one-use, with atomic consumption.
- Template pages and JSON endpoints share business logic. APIs return JSON errors instead of HTML login redirects. Keep CSRF active; default same-site architecture.
- Username, email, and phone login must resolve to the same user; do not auto-merge or auto-create accounts on code login.
- Group 10 only prepares contact/message extensions. Group 11 implements code workflows and is optional later work, not implied scope of Nov 10 acceptance.
- Development senders cannot run in production or return codes from public APIs. Do not send real messages, buy services, or publicly deploy without user authorization.
- Keep secrets/local database out of Git. Record important maintenance actions without secrets.

## Verification

Use actual PostgreSQL for schema, uniqueness, transaction, and concurrency verification; explicit CSRF enforcement in relevant tests. Label unrun browser/load/deployment checks as unverified. A successful process liveness response does not prove DB readiness or 100-user capacity. Never claim a group complete with required acceptance checks still failing.

## Mandatory autonomous review before every group handoff

The user explicitly requires proactive omission checks without reminders. This is part of implementation, not an optional follow-up.

1. Before coding, identify the acceptance criteria and relevant failure paths for the current group.
2. After coding, reread the actual changed code and its immediate callers, middleware, and database effects; do not only reread passing tests.
3. For relevant behavior check invalid/missing input, normalization, forbidden fields, unauthorized access, concurrency/duplicate requests, rollback, dependency failure, secret-safe responses/logs, and isolation of development/test data.
4. Review framework behavior outside the view/service boundary. When applicable include pre-view parsing, cache/cookies, session lifecycle, and commands that can bypass the usual entry point.
5. For a reproduced defect add a regression test when practical, fix it, then run the affected tests and required regression checks. Do not repeatedly broaden tests without a new change or unresolved concern.
6. Reconcile every current acceptance item with evidence. Keep unresolved defects distinct from explicitly deferred functionality and deployment prerequisites. Do not invent new requirements merely to report a finding.
7. Ensure relevant migrations and the running local service match the code, and record limitations. Update PROGRESS.md and the review record, then save a local checkpoint after checking secrets.
8. Report briefly: completed result, material limitation, next step. Never promise zero omissions or treat a passing test count as proof of completeness. Do not rely on the user to request this review.

Current review boundaries and deferred deployment checks are in docs/REVIEW.md.
