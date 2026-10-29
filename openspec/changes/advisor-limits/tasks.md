## Progress checklist

Branch `claude/advisor-rate-limit`.

- [x] 1.1 Redis in `compose.yaml`, `deploy/compose.prod.yaml` and CI
- [x] 1.2 Red/green: client IP only from a trusted proxy (forged header ignored)
- [x] 1.3 Red/green: sliding windows per subject and IP (switching account still blocked)
- [x] 1.4 Red/green: daily token caps (subject, IP, site) and usage accounting
- [x] 1.5 Red/green: Redis down returns 503
- [x] 1.6 Red/green: `max_tokens` reaches the request body
- [x] 1.7 Review fixes: detached turns, reservations, admission after validation, re-resolve on miss
- [x] 2.1 Web: the 429/503 message is shown; a refused confirm can be answered again
- [x] 3.1 Caddy sets `X-Forwarded-For` explicitly
- [x] 3.2 Local load test: blocked ratio and limit-check p99
