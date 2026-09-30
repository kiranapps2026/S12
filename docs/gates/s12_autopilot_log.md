# S12 autopilot log (append only)

`<commit> | Mxx | <check> | <PASS>/<total> | <summary>`

bca563b | M1 | S12-PIN | 4/6 | STOP-001: golden set not pinned (owner action)
4fa314c | M1 | G-M1 | 5/7 | enums + migration 015: golden M1 89/89, sabotage 4/4; S12-PIN and S12-REC wait on the owner pin (STOP-001)
MILESTONE M1 REACHED at 4fa314c except owner-only rows S12-PIN, S12-REC (unpinned by owner decision)
690e6ad | M1 | full | 6/7 | after owner pin abfff2f: S12-PIN PASS; only S12-REC (STOP-001 awaiting owner "applied") remains
838ebcf | M2 | full | 8/9 | fenced_write + transition log + settings; golden M2 18/18, x5, sabotage 3/3; tests 836, tests_postgres 330
MILESTONE M2 REACHED at 838ebcf except S12-REC (STOP-001 awaits owner "applied")
b9e6123 | M3 | full | 9/10 | validator with reasons for run/step/reservation; golden M3 130/130, sabotage 3/3; tests 836, tests_postgres 330
MILESTONE M3 REACHED at b9e6123 except S12-REC (STOP-001)
8f38edb | M4 | full | 10/11 | all nine machines + no bare state literals; golden M4 79/79, sabotage 2/2; tests 836, tests_postgres 330
MILESTONE M4 REACHED at 8f38edb except S12-REC (STOP-001)
8f38edb | M5 | G-M5 | - | STOP-002: no B2 golden file for M5
77c26e2 | M5 | full | 11/13 | C20 entry check; golden M5 30/30, x5, sabotage 3/3; tests 836, tests_postgres 330 (after supplying the reader in the tests_postgres _admit helper: 2 confirmed-run tests had been denied, correctly, without one)
MILESTONE M5 REACHED at 77c26e2 except owner rows S12-PIN (B2 unpinned) and S12-REC (STOP-001, STOP-002)
6091a87 | M6 | full | 12/14 | DEF-001 fixed; golden M6 23/23, sabotage 3/3; tests 836, tests_postgres 330 (prototype log-order expectation updated)
MILESTONE M6 REACHED at 6091a87 except owner rows S12-PIN (B2 unpinned) and S12-REC (STOP-001, STOP-002)
62f8ebb | M7 | full | 14/16 | leases, fencing, ownership; golden M7 15/15, x5, sabotage 5/5; agent 15 (found and fixed: load not resynced when an acquisition expired leases then refused); tests 836, tests_postgres 330
MILESTONE M7 REACHED at 62f8ebb except owner rows S12-PIN (B2 unpinned) and S12-REC (STOP-001, STOP-002)
6e49b7a | M8 | full | 15/17 | admission controller and selection; golden M8 39/39, sabotage 4/4; agent 27 (mutation-checked); tests 836, tests_postgres 330; note for M12: retry delays to settings (§21 S1)
MILESTONE M8 REACHED at 6e49b7a except owner rows S12-PIN (B2 unpinned) and S12-REC (STOP-001, STOP-002)
24e2296 | M8a | full | 16/18 | filters, selection reader, quota settings; golden M8a 49/49, x5, sabotage caught; agent 35 (mutation-checked); tests 836, tests_postgres 330 (schema audit: date_part, not extract FROM); CONF-019, CONF-020, STOP-003 opened
MILESTONE M8a REACHED at 24e2296 except owner rows S12-PIN (B2 unpinned) and S12-REC (STOP-001, STOP-002, STOP-003; CONF-019, CONF-020) — ★ STOP for owner review
