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
Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'; ...
Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
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
| Global (all routes) | 100 req | 15 min |
| Login/signup | 5 req | 15 min |
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
