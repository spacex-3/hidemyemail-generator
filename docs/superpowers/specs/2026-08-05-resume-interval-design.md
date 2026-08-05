# Resume Interval Update Design

## Goal

When a stopped account's interval input is edited, Resume must use the edited interval while preserving the existing target and completed progress.

## Root Cause

Start sends `{count, interval}` and stores the interval in `Progress`. Resume sends no request body and `GenerationManager.resume_account` accepts no interval. Once the task is running, status polling replaces the edited input with the old stored interval.

## Design

- `rsA` reads the account's interval input and sends `{interval}` as JSON.
- `handle_resume` parses and validates the interval, then passes it to the manager.
- `resume_account(apple_id, interval)` stores the interval before scheduling the remaining work.
- Interval values below 30 are normalized to 30, matching the existing cooldown minimum. Missing or invalid values use the currently stored interval for backward compatibility.
- Target, completed count, generated history, and cycle progress remain unchanged.

## Tests

Unit tests verify that Resume updates the interval to 66 without resetting progress and that a missing interval preserves the old value. A server source assertion verifies the browser sends the interval in the Resume request.
