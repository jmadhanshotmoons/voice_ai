# Batkarai pricing: market comparison and what we charge

Researched November 2026. Competitor figures come from their own docs where possible and from third-party blogs otherwise, and they disagree with each other, so treat them as ranges. Conversion used: about Rs 88 per US dollar.

## What we charge

| Item | Price |
|------|-------|
| Standard voice (Sarvam) | **Rs 5 per connected minute** |
| Premium voice (Cartesia, most lifelike) | **Rs 6.8 per connected minute** |
| Billing | 30-second blocks, minimum one block. Unanswered calls free. 18% GST extra |
| Free credits | 50 on signup (10 minutes of standard calls) |
| Smallest top-up | Rs 499 (was Rs 1,499) |
| Credit packs | Rs 499, 999 (+50), 2,499 (+150), 9,999 (+800), 24,999 (+2,500), 50,000 (+6,000) |
| Number rental | Rs 649 per month per channel (unchanged, see "To verify") |

The code, the dashboard and the website now all use the same Rs 5 / 6.8. Before this change the billing code charged Rs 3.6 / 5.5 while the website advertised Rs 5 / 6.8.

## How competitors price

| Platform | Published price | What it includes | Roughly in rupees |
|----------|-----------------|------------------|-------------------|
| [Sarvam Voice Agents](https://docs.sarvam.ai/voice-agents/pricing) | Rs 3.50/min pay-as-you-go, Rs 3.25/min on Pro (Rs 9,999 minimum) | Platform, speech, language and voice models. Telephony extra (Rs 0.20 per 30 s), number Rs 59 per 30 days. Billed in whole minutes | Rs 3.9 with telephony |
| [Bolna](https://www.bolna.ai/docs/pricing/call-pricing) | $0.02/min platform + model costs + telephony | Third-party reports put it at Rs 5.5 to 7 per minute, falling to about Rs 3 at volume | Rs 5.5 to 7 |
| [Ringg](https://www.ringg.ai/ai-voice-agent-pricing) | One rate per connected minute, whole stack | Its own example works out to about Rs 6 per minute | about Rs 6 |
| Raya | From Rs 3.50/min | Per a third-party review | Rs 3.5 and up |
| [Vapi](https://zeeg.me/en/blog/post/vapi-ai-pricing) | $0.05/min platform fee, speech, model and voice at cost | All-in estimates $0.10 to $0.33 per minute | Rs 9 to 29 |
| [Retell](https://eesel.ai/blog/retell-ai-pricing) | $0.07 to $0.31/min, parts billed separately | Typical support call about $0.114 | Rs 6 to 27, typically Rs 10 |
| Indian market overall | Rs 2 to 12 per minute, Rs 3 to 6 most common for mid-market ([guide](https://ecorpit.com/ecorpit-ai-voice-agent-development-service-india-2026/)) | Some add Hindi or telephony surcharges | |

Where Batkarai sits: **below Bolna, Ringg and the US platforms for an all-inclusive rate, and Rs 1 to 1.5 above Sarvam's own bare platform rate**. Unlike Sarvam's rate, ours includes the phone line and no separate model or telephony bill. Premium (Rs 6.8) is still below Retell's typical call and far below Vapi's all-in cost.

## Our own cost per minute (estimates)

| Part | Basis | Rs per minute |
|------|-------|---------------|
| Speech recognition | Sarvam Rs 30 per hour of audio | about 0.5 |
| Voice, standard | Sarvam Bulbul v3, Rs 30 per 10,000 characters, agent speaks about 380 characters per minute | about 1.1 |
| Voice, premium | Cartesia, $38 to $65 per million characters ([pricing](https://cartesia.ai/pricing)) | 1.3 to 2.2 |
| Language model | Claude Haiku 4.5 on Bedrock, about 12k input tokens per minute (our estimate, not measured) | about 1.2 |
| Phone line, Twilio India mobile | $0.0496 per minute ([Twilio](https://www.twilio.com/en-us/voice/pricing/in)) | **about 4.4** |
| Phone line, Indian carrier | Sarvam telephony benchmark Rs 0.20 per 30 s | about 0.4 |
| Phone line, web test call | browser, no carrier | 0 |

| Call type | Our cost | Standard margin at Rs 5 | Premium margin at Rs 6.8 |
|-----------|----------|-------------------------|---------------------------|
| Web call | Rs 2.8 to 3.9 | about 44% | 43% to 56% |
| Phone, Indian carrier | Rs 3.2 to 4.3 | about 36% | 37% to 50% |
| Phone, **Twilio** | Rs 7.2 to 8.3 | **about -44% (loss)** | **about -9% to -22% (loss)** |

## Recommendation

1. **Keep Rs 5 and Rs 6.8.** It is competitive and leaves a healthy margin, but only on cheap telephony.
2. **Do not scale on Twilio for India.** Twilio's own per-minute charge is almost the whole standard price. Use Twilio for testing and trials, and move live Indian traffic to an Indian carrier (the Exotel adapter already exists in the code). With the current Rs 5 price, every standard Twilio call to an Indian mobile loses about Rs 2.2.
3. **Cheap wins to widen the margin:** switch standard voice to Bulbul v2 (half the voice cost), turn on prompt caching for the language model (the long system prompt repeats every turn), and keep the 30-second block billing.
4. **Volume deals:** quote Rs 3.5 to 4 per minute only to customers on Indian carrier lines at volume. Rs 3.5 is at cost on Twilio.

## To verify before relying on these

- Exotel's real per-minute rate (not searched here; the Rs 0.4 figure is Sarvam's carrier benchmark).
- Twilio's India number rental price. Rs 649 per month per channel is much higher than Sarvam's Rs 59 per 30 days; lower it once you know your real cost.
- Actual language-model token use per minute from a few real calls.
- Current competitor pages. The figures above change often.
