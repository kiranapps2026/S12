# M7: leases, fencing, ownership (gate commit E, part 1) ⚙ (built)

| | |
|---|---|
| Status | Built in `62f8ebb`. Golden 15/15, x5 (C-M7 PASS), sabotage 4/4. The agent's own tests found and fixed one defect: the load was not resynced when an acquisition expired leases and then refused |
| Gate | C5 (acquisition transaction, capacity, `current_load`), C25 (one sequence, per-execution fence), C26 (stored lease status; usable = `active AND expires_at > now()`; expiry by the next acquisition; no renewal after expiry), suite 5; WORKER_LIFECYCLE §14 (ownership transfer: strictly greater token, compare-and-set); invariants I5, I7, I8 |
| Golden | `tests_golden/s12/M07_leases.py`: 15 cases, 14 functions; 5 consecutive runs |
| Sabotage (4) | `M07_per_worker_token`, `M07_renew_after_expiry`, `M07_stale_leases_counted`, `M07_steal_live_execution` (helper `_lease_base.py`) |

## File (as built)

`src/adapters/postgres/leases.py`:

- `Lease(lease_id, tenant_id, worker_id, execution_id, fence_token)` (frozen, :63).
- `LeaseLost` (:72).
- `PostgresLeaseManager(database)` (:82):

```python
async acquire(*, tenant_id, worker_id, execution_id, runtime_instance_id, ttl_s) -> Lease | None   # :86
async renew(lease, *, runtime_instance_id, ttl_s) -> Lease                                       # :121
async release(lease, *, reason) -> bool                                                          # :148
```

Writes for the execution then use `fenced_write` with `FenceHolder(..., fence_token=lease.fence_token)`.

## Logic and conditions

**`acquire`, ONE transaction:**

1. Lock the worker row (`FOR UPDATE`).
2. Expire that worker's stale leases: `active → expired` (reason `ttl_elapsed`, logged). Leases past `expires_at`
   are **never** counted as active (sabotage `M07_stale_leases_counted`).
3. Count its **usable** leases. Proceed only if the count is below `capacity`, the worker is `ACTIVE`, and the
   execution has **no other usable lease** (one owner at a time; sabotage `M07_steal_live_execution`). Otherwise
   return `None` and write nothing (the load is resynced).
4. Take the token from **`fence_token_seq`**, never `max()+1` per worker (sabotage `M07_per_worker_token`).
5. Insert the lease `active` (logged `None → active`, `acquired`, with the new token in
   `state_transitions.fence_token`). Set `workers.current_load` to the new count and `workers.lease_epoch` to the
   token.
6. Move `execution_ownership` (worker, lease, runtime, token) by **compare-and-set** to the new, strictly greater
   token.

**`renew`:** only while the lease is usable. It takes a **new token from the sequence**, moves ownership by
compare-and-set from the old token, and logs `active → active` (`renewed`). After `expires_at`, or by a released
holder → `LeaseLost` (sabotage `M07_renew_after_expiry`). Renewing one lease **never fences other executions** on the
same worker (the fence is per execution).

**`release(lease, *, reason)`:** `active → released` with `work_complete`, `fenced_out` or `run_terminal`, and it
decrements `current_load` in the same transaction.

**Guarantees the golden checks:**

| Property | Check |
|---|---|
| capacity 1 and 3 never exceeded under concurrency | 5 runs |
| `current_load` = usable leases | every move |
| tokens strictly increase per worker **and** per execution, in issue order | I8 from the log |
| a takeover by another worker gets a larger token and fences the old owner | stale owner's writes affect 0 rows |
| no `active` lease for a terminal run; no lease goes `expired → active` | I7 |
| every lease move is logged with its reason | I5 |

**Where "one owner at a time" is enforced:** there is **no** unique index on active leases per execution. The rule
holds because `acquire` locks the ownership row (`FOR UPDATE`) and checks for a usable lease inside that lock, so two
acquisitions for the same execution serialize. Any new code that inserts into `worker_leases` must go through
`acquire`, or the rule fails silently (I7/I8 in the invariant checker are what would notice).

## Sabotage

| Patch | Breaks |
|---|---|
| `M07_per_worker_token` | tokens per worker (`max+1`): a takeover by another worker gets a smaller token |
| `M07_renew_after_expiry` | a lease past `expires_at` still renews |
| `M07_stale_leases_counted` | expired-in-fact leases still count toward capacity |
| `M07_steal_live_execution` | no check for an existing usable lease: two owners at once |

## Later additive changes (do not break M07)

- M12 adds `acquire(..., holder=None)`: with a holder, the ownership row is checked under its lock and `FencedOut`
  is raised when ownership moved (CONF-033).
- M19 adds `acquire(..., skip_locked=False)` and `expire_lapsed(tenant_id, execution_id)`.

With the defaults, behaviour is exactly M07's.

## Traps

- Per-worker token counters; `max(fence_token)+1`.
- Expiring leases by a timer. The **next acquisition** expires them (C26).
- Renewal that reuses the old token.

## Regression checklist

- [ ] 15/15, 5 runs in a row; 4 patches caught; I7, I8 hold.
