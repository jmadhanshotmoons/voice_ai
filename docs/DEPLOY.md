# Deploying VoiceAI

| Part | Where | Config |
|---|---|---|
| Web app (Next.js) | Vercel | `apps/web` |
| API + voice server + Redis | Render | `render.yaml` (Blueprint) |
| Database + login | Supabase (hosted) | `packages/db/migrations/001-008` |
| Phone calls | Twilio (or Exotel) | env vars on Render |

Live frontend: https://voiceai-web-gamma.vercel.app (Vercel project `voiceai-web`).

## 1. Supabase (hosted)
1. Create a project at supabase.com.
2. SQL editor: run `packages/db/migrations/001` to `008` in order.
3. Authentication -> URL Configuration: set Site URL to the Vercel URL and add it to Redirect URLs.
4. Copy the project URL, `anon` key and `service_role` key (Settings -> API).

## 2. Render (backend)
1. Render dashboard -> New -> **Blueprint** -> pick this repo. It reads `render.yaml` and creates
   `voiceai-api`, `voiceai-voice` and `voiceai-redis` in Singapore.
2. Fill the variables marked `sync: false`:
   - both services: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `FRONTEND_URL` (the Vercel URL)
   - `voiceai-voice`: `SARVAM_API_KEY`, `CARTESIA_API_KEY`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
   - `voiceai-api`: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, Razorpay keys
3. If Render names the services differently from `voiceai-api` / `voiceai-voice`, update
   `PUBLIC_API_URL` and `PUBLIC_VOICE_URL` on the API to the real https URLs.
4. Use the `starter` plan. Free web services sleep when idle and would drop phone calls.

## 3. Vercel (frontend)
The project is already created and deployed. Replace the two placeholder variables, then redeploy:
```bash
cd apps/web
printf '%s' 'https://YOUR-PROJECT.supabase.co' | vercel env add NEXT_PUBLIC_SUPABASE_URL production --force
printf '%s' 'YOUR-ANON-KEY'                   | vercel env add NEXT_PUBLIC_SUPABASE_ANON_KEY production --force
vercel deploy --prod --yes
```
`NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_VOICE_SERVER_URL` already point at the Render names above.
Never set `NEXT_PUBLIC_DEV_LOGIN` in production.

To deploy on every push, connect the GitHub repo in Vercel and set Root Directory to `apps/web`.

## 4. Twilio
- Outbound calls need nothing configured in Twilio: the API passes the URLs on each call.
- Trial accounts can only call numbers verified in the Twilio console, and play a trial message first.
- For inbound calls, set the number's Voice webhook (HTTP POST) to
  `https://voiceai-api.onrender.com/api/v1/telephony/twilio/inbound` and add the number under Numbers
  in the dashboard, assigned to an employee.
- Calls to countries other than India are blocked by default (`CALL_ALLOWED_PREFIXES`).

## Testing phone calls from your own computer
```bash
bash scripts/dev-tunnels.sh   # public https URLs for the local API and voice server, written to .env
```
Restart the API and voice server, set `TELEPHONY_PROVIDER=twilio` and the three `TWILIO_*` values in
`.env`, then use "Call a phone" in the dashboard.
