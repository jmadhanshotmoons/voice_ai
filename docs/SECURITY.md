# Security Architecture

## Threat Model (based on real vulnerabilities found in similar platforms)

### Attack Surface Map

| Surface | Threats | Defenses |
|---------|---------|----------|
| **Auth (Supabase JWT)** | Token theft, weak passwords, mass signup | PKCE flow, rate-limited signup (3/hr), password policy |
| **API routes** | IDOR/BOLA, mass assignment, injection | Account-scoped queries, Zod validation, input sanitization |
| **Admin routes** | Privilege escalation via regular JWT | Separate is_admin check in middleware, admin routes return 404 for non-admins |
| **WebSocket (voice)** | Unauthorized call access, audio interception | JWT auth on connection, call_id tied to account |
| **Webhook intake** | Forged leads, DoS via flood | HMAC-SHA256 signature, rate limit 60/min |
| **Payments (Razorpay)** | Forged payment confirmation, price tampering | Server-side amount from CREDIT_PACKS, HMAC signature verification |
| **Credit system** | Race condition (double-spend), negative balance | PostgreSQL FOR UPDATE lock in stored procedure |
| **Frontend** | XSS, clickjacking, CSRF | CSP headers, X-Frame-Options DENY, SameSite cookies |
| **Secrets in JS bundle** | API key exposure | All keys server-side only. Frontend uses ONLY Supabase anon key (by design) |
| **Cloud storage** | Public bucket exposure | No public buckets. Signed URLs for recordings with expiry |
| **Employee config** | Prompt injection via system prompt | User prompts sandboxed in LLM context. No eval() or template injection |
| **Phone numbers** | Enumeration, toll fraud | Numbers tied to accounts. Outbound calls require credit balance |

## Lessons Applied from Real Assessments

### From Outpero assessment (28 findings):
1. **Supabase anon key in JS** -- We accept this (by design) but lock down PostgRES with RLS policies
2. **No rate limiting on signup** -- We enforce 3 signups/hr/IP
3. **Admin panel with password-only auth** -- We use Supabase JWT + is_admin flag, no separate admin password
4. **Admin API endpoints same as user** -- We use requireAdmin middleware that returns 404 (not 403) to non-admins
5. **100+ endpoints in JS bundle** -- Our frontend only knows the API base URL. Routes are not enumerable from client
6. **User enumeration via signup** -- Supabase default; we accept this as low risk for an Indian B2B SaaS

### From Rival.io assessment (9 findings):
1. **Public cloud buckets** -- All storage uses signed URLs with expiry
2. **Sitemap leaking emails** -- No PII in URLs. UUIDs for all public identifiers
3. **Default credentials in installer** -- All secrets generated randomly. No defaults
4. **CORS wildcard** -- Strict origin allowlist in CORS config
5. **CI/CD exposure** -- No public CI/CD. GitHub Actions with environment protection

## Security Headers (set by Helmet)

```
Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; ...   (API; the web app uses a per-request nonce CSP)
Strict-Transport-Security: max-age=63072000; includeSubDomains; preload
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
X-XSS-Protection: 0  (deprecated, CSP replaces it)
```

## Input Validation

Every POST/PATCH request body is validated with Zod schemas that:
- Strip unknown fields (prevents mass assignment: {"is_admin": true})
- Enforce type + length constraints
- Reject NoSQL operators ($ne, $gt, $regex)
- Reject prototype pollution keys (__proto__, constructor)

## Rate Limits

| Endpoint | Limit | Window |
|----------|-------|--------|
| Global (all routes) | 100 req | 1 min |
| Sensitive (account delete, outbound call tickets) | 10 req | 1 min |
| Lead intake | 60 req | 1 min |
| Signup | 3 req | 1 hour |

## Secrets Management

- All secrets in .env file (gitignored)
- Frontend ONLY has NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY
- Supabase service key is backend-only
- AWS credentials are backend-only (voice server)
- Razorpay secret is backend-only
- Webhook secrets generated server-side with crypto.randomBytes(32)
- JWT verification uses Supabase's built-in verification (HS256 with project secret)

## Database Security

- Row Level Security (RLS) on ALL tables
- account_id derived from JWT (auth.uid() -> accounts.auth_user_id), never from request body
- Credit operations use FOR UPDATE row locks to prevent race conditions
- Stored procedures for atomic credit add/deduct


## Hardening checklist: what is in the code, and what you switch on at deployment

### Done in code
| Area | What |
|------|------|
| Headers | API, voice server and web app send HSTS (2y, preload), CSP, nosniff, X-Frame-Options DENY, Referrer-Policy, Permissions-Policy, COOP/CORP/COEP, `Cache-Control: no-store`. No `Server`/`X-Powered-By`. Web CSP uses a per-request nonce: no `unsafe-eval`, no inline scripts. Documented exception: `style-src 'unsafe-inline'` (React/framer-motion style attributes). Web keeps `microphone=(self)` because test calls need it. |
| CORS | Explicit origin list from `FRONTEND_URL` (comma separated), never `*`, origin never reflected, methods limited, preflight cached 10 min. Voice server also checks WebSocket `Origin`. |
| CSRF | Auth is a bearer token (no cookie to ride), plus `Origin` verification on every browser write. |
| Auth | Sign-up needs 12+ characters and is checked against Have I Been Pwned (k-anonymity). Supabase config: min length 12, upper+lower+digits, 15-min access tokens, refresh-token rotation, TOTP MFA on, 24h timebox, 30-min inactivity. Passwords are hashed by Supabase (bcrypt). Sign-in failures return the same generic message. |
| Sensitive actions | Account deletion re-checks the password and requires typing `DELETE`. |
| Voice server | Browser calls need a 60-second HMAC ticket minted by the authenticated API for an employee the caller owns. The anonymous demo agent is no longer reachable. API docs/OpenAPI disabled. |
| API | Auth on every route except health, signed phone webhooks, API-key lead intake. Per-account scoping on every query (IDOR). Zod validation, 1 MB body limit, paginated lists with caps, parameterised queries only (Supabase client), method allow-list (no TRACE), `/health` returns `{"status":"ok"}` only. |
| Errors and logs | Generic errors to clients. One JSON log line per request (time, IP, user, status, path only; secrets, tokens, emails, phone numbers redacted). Auth failures and denied access logged as warnings. |
| Privacy | `/privacy` page, no analytics (no consent banner needed), account deletion (`DELETE /api/v1/account`, migration 009), 180-day transcript retention function. |
| Supply chain | Lockfiles committed, unused/typosquat-risk packages removed (`crypto`, `morgan`, `winston`, `express-mongo-sanitize`), Dependabot, `npm audit` + `pip-audit` + gitleaks + CodeQL in CI with actions pinned to commit SHAs. `.env` git-ignored. Non-root containers. |
| Discovery | `/.well-known/security.txt` on the API and the web app. Add `Canonical:` and `Policy:` once the domain exists. |

### Do at deployment (dashboard settings, not code)
| Item | How |
|------|-----|
| TLS 1.2+/1.3, auto-renewing certs, HTTP to HTTPS | Render and Vercel do this by default. |
| WAF / DDoS | Put Cloudflare in front of the custom domain (free plan: OWASP managed rules, DDoS). |
| MFA enforcement, HIBP check, session timebox | Supabase hosted: Auth > Providers/Policies (leaked-password protection, timebox and inactivity are Pro-plan features). |
| Run migration 009 and schedule retention | `select cron.schedule('purge-calls','0 3 * * *', $$select public.purge_old_call_content(180)$$);` (enable pg_cron). |
| Database not public, TLS, backups | Supabase hosted is TLS-only; enable daily backups (Pro) or schedule `pg_dump` to encrypted storage. Test a restore. |
| Separate dev/staging/prod, different secrets each | Separate Supabase projects and Render env groups. Rotate every 90 days (calendar reminder). |
| SPF / DKIM / DMARC / CAA / DNSSEC | At the DNS host once you own the domain: `v=spf1 include:<mail provider> -all`, DKIM from the mail provider, `v=DMARC1; p=reject; adkim=s; aspf=s; rua=mailto:dmarc@<domain>`, CAA `0 issue "letsencrypt.org"`. |
| Branch protection | GitHub: Settings > Branches > require PR review, block force pushes. |
| Uptime and alerts | UptimeRobot/Better Stack on `/health`; alerts on auth-failure spikes from the JSON logs (Render log streams to Datadog/Better Stack). |
| Incident response plan | Keep a one-page runbook: rotate keys, revoke sessions (Supabase), disable telephony number. |

### Known gaps (honest list)
- Web session lives in browser storage via supabase-js, not an HttpOnly cookie. Moving to `@supabase/ssr` cookies is the next step; the nonce CSP is the main XSS defence until then.
- Supabase signs JWTs with HS256 by default; hosted projects can switch to asymmetric signing keys (RS256/ES256) in the dashboard. The API validates tokens through Supabase (`getUser`), which checks signature, issuer and expiry.
- Server-side account lockout after 10 failures and email unlock are Supabase Auth features, tuned in the dashboard rate limits, not custom code.
- Two moderate npm advisories remain in `node-cron`'s `uuid` dependency (not reachable from our usage); Dependabot will propose the fix.
