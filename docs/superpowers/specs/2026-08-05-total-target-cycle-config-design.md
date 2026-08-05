# Total Inventory Target and Configurable Cycle Size Design

## Goal

Make each account's target represent its final local Hide My Email inventory and let the operator configure the number generated per cooldown cycle from the dashboard.

## Root Causes

- `Progress.load_historical_emails()` correctly loads saved addresses, but `Progress.reset()` sets `completed` to zero. A target of 600 therefore schedules 600 new addresses and displays `0/600` even when the account already has saved addresses.
- `Progress.cycle_size` is exposed in status JSON, but `RichHideMyEmail.generate()` uses the global `CYCLE_SIZE` constant for batch capacity, progress logs, and cooldown decisions. The effective cycle therefore remains 5.
- The dashboard has no cycle-size input, and the Start and Resume requests cannot carry an account-specific value.

## Considered Approaches

1. Use the saved email file as the inventory source and store the chosen cycle size in `Progress`. This is the selected approach because the dashboard's Total already comes from this history, it supports different settings per account, and it preserves settings across Stop/Resume within the running process.
2. Query Apple's server for the active alias count before every Start. This could discover aliases created elsewhere, but it changes the meaning of the existing Total, adds network/API risk, and is outside this request.
3. Configure one global cycle size through Docker Compose. This is simple but cannot support account-specific controls and does not satisfy the frontend requirement.

## Behavior

### Total target

- Start and Restart interpret `count` as the desired final inventory total.
- At Start, `existing = len(progress.emails)`, `completed = existing`, and `remaining = max(0, target - existing)`.
- A saved history of 73 with target 600 schedules exactly 527 new addresses and displays `73/600` before the first new address succeeds.
- Starting with a target less than or equal to existing history schedules no generation task, sets status to `done`, and reports that the target is already reached.
- Existing email history is never cleared by Start or Restart.
- If existing history exceeds the target, the actual count remains visible (for example `650/600`) and progress bar widths are clamped to 100 percent.

### Cycle size

- Each authenticated account card has a `每轮` numeric input, defaulting to 5 and accepting integers from 1 through 999.
- Start and Resume submit `cycle_size`; the server validates it as an integer and the manager clamps it to at least 1.
- Start resets `success_in_cycle` to zero and stores the selected cycle size.
- Resume preserves `success_in_cycle` and applies the currently entered cycle size. For example, resuming from `5/5` with 15 selected continues at `5/15` until 10 more successes trigger cooldown.
- Batch capacity, startup and progress logs, and proactive cooldown checks all use `progress.cycle_size`.
- Requests that omit `cycle_size` remain compatible: Start defaults to 5 and Resume keeps the stored value.

## Data Flow

The dashboard reads target, interval, and cycle inputs. Start posts `{count, interval, cycle_size}` and Resume posts `{interval, cycle_size}`. The aiohttp handlers parse the fields and pass them to `GenerationManager`. The manager updates `Progress`, computes remaining work from saved history, and the generation loop reads the account's stored cycle size.

## Error Handling

- Invalid or missing Start target follows the existing positive-target validation path.
- Invalid cycle-size JSON falls back to the compatible default on Start or preserves the current value on Resume.
- Authentication and HME context validation remain unchanged.
- No task is created when the requested total is already met.

## Tests

- Manager tests cover `73 -> 600` scheduling 527, initial progress `73/600`, and no task when history already meets or exceeds the target.
- Generation-loop tests prove a cycle size of 15 allows work beyond 5 without starting a long cooldown.
- Manager and handler tests cover Start and Resume propagation, minimum normalization, and preservation of cycle progress.
- Dashboard source assertions cover the new input and both JSON request bodies.
- The full unit suite and Docker build must pass before push.
