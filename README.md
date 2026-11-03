# VoiceAI -- AI Calling Platform

AI employees that make your business calls in 7 Indian languages.

## Architecture

```
Browser (Next.js) --> API Server (Express) --> Voice Pipeline (FastAPI/WebSocket)
                          |                         |
                     Supabase (DB/Auth)        ASR: Sarvam AI
                     Redis (state)             LLM: AWS Bedrock (Claude)
                     Razorpay (payments)       TTS: Cartesia / Sarvam
                                               Tel: Exotel
```

## Quick Start

### 1. Prerequisites
- Node.js 20+
- Python 3.11+
- Redis 7+
- Docker (optional)

### 2. Clone and install
```bash
git clone <repo>
cd VoiceCallingAgent

# Start Redis
docker-compose up -d redis

# Voice server (Python)
cd apps/voice-server
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# API server (Node.js)
cd ../api
npm install

# Frontend (Next.js)
cd ../web
npm install
```

### 3. Configure environment
```bash
cp .env.example .env
# Fill in ALL keys (see below)
```

### 4. Set up database
Run the SQL files in `packages/db/migrations/` in order (001-008) in your Supabase SQL editor.

### 5. Start all services
```bash
# Terminal 1: Voice pipeline
cd apps/voice-server && python -m src.main

# Terminal 2: API server
cd apps/api && npm run dev

# Terminal 3: Frontend
cd apps/web && npm run dev
```

Open http://localhost:3000

## Deploying
See `docs/DEPLOY.md` (Vercel for the web app, Render for the backend, Supabase for the database, Twilio for calls).

## Required API Keys

| Key | Where to Get | Free Tier |
|-----|-------------|-----------|
| SARVAM_API_KEY | indus.sarvam.ai | Free credits on signup |
| CARTESIA_API_KEY | play.cartesia.ai | 20K credits/month free |
| AWS_ACCESS_KEY_ID | AWS IAM Console | Bedrock pay-per-use |
| AWS_SECRET_ACCESS_KEY | AWS IAM Console | Bedrock pay-per-use |
| SUPABASE_URL | supabase.com | Free tier (500MB) |
| SUPABASE_ANON_KEY | supabase.com | Included |
| SUPABASE_SERVICE_KEY | supabase.com | Included |
| RAZORPAY_KEY_ID | dashboard.razorpay.com | Test mode free |
| RAZORPAY_KEY_SECRET | dashboard.razorpay.com | Test mode free |

## Security Hardening

This platform was built with security as a primary concern, informed by real vulnerability assessments of similar platforms. See `docs/SECURITY.md` for details.

Key defenses:
- JWT auth on every route with account-level scoping (IDOR prevention)
- Rate limiting on all endpoints (brute force prevention)
- Separate admin auth with role checks (BOLA prevention)
- Zod input validation stripping unknown fields (mass assignment prevention)
- HMAC-SHA256 webhook signatures (forgery prevention)
- Timing-safe comparisons for all secret checks
- CSP, HSTS, X-Frame-Options security headers
- No version/stack disclosure in responses
- Atomic credit operations with DB-level locks (race condition prevention)
- NoSQL operator stripping from all inputs
- Prototype pollution prevention in body parser

## Project Structure

```
apps/
  web/          Next.js frontend (dashboard, auth, landing)
  api/          Express API server (routes, auth, billing)
  voice-server/ Python FastAPI voice pipeline (ASR, LLM, TTS)
packages/
  db/           SQL migrations for Supabase
  shared/       Shared TypeScript types
```

## Supported Languages
Hindi, Telugu, Tamil, Kannada, Malayalam, Marathi, English

## Per-Minute Cost (self-hosted)
- Budget tier (Sarvam TTS): ~Rs 3.50/min
- Premium tier (Cartesia TTS): ~Rs 7.00/min

## License
Private. Not for redistribution.
