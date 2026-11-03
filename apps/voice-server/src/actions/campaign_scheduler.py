"""Campaign scheduler -- processes bulk calling campaigns.

Runs as a background task. For each active campaign:
1. Checks calling hours
2. Picks next contact to call
3. Checks DND registry
4. Initiates call via telephony bridge
5. Updates contact status
6. Handles retries on failure/no-answer
"""

import asyncio
import time
from datetime import datetime, timezone, timedelta
import structlog

logger = structlog.get_logger()

IST = timezone(timedelta(hours=5, minutes=30))


class CampaignScheduler:
    """Processes bulk campaigns in the background."""

    def __init__(self, supabase_client, telephony_service):
        self.db = supabase_client
        self.tel = telephony_service
        self.running = False
        self.check_interval = 10  # seconds between checks

    async def start(self):
        """Start the campaign processing loop."""
        self.running = True
        logger.info("campaign_scheduler_started")

        while self.running:
            try:
                await self._process_active_campaigns()
            except Exception as e:
                logger.error("scheduler_error", error=str(e))

            await asyncio.sleep(self.check_interval)

    async def stop(self):
        self.running = False
        logger.info("campaign_scheduler_stopped")

    async def _process_active_campaigns(self):
        """Find active campaigns and process next contacts."""
        # Get active campaigns
        result = self.db.table("campaigns").select("*").eq("status", "active").execute()
        campaigns = result.data or []

        now = datetime.now(IST)

        for campaign in campaigns:
            # Check calling hours
            hours = campaign.get("calling_hours", {})
            start_hour = int(hours.get("start", "09:00").split(":")[0])
            end_hour = int(hours.get("end", "18:00").split(":")[0])

            if now.hour < start_hour or now.hour >= end_hour:
                continue  # Outside calling hours

            # Get next pending contact
            contact_result = (
                self.db.table("campaign_contacts")
                .select("*")
                .eq("campaign_id", campaign["id"])
                .eq("status", "pending")
                .order("created_at")
                .limit(1)
                .execute()
            )

            contacts = contact_result.data or []
            if not contacts:
                # All contacts processed -- mark campaign complete
                self.db.table("campaigns").update({"status": "completed"}).eq(
                    "id", campaign["id"]
                ).execute()
                logger.info("campaign_completed", campaign_id=campaign["id"])
                continue

            contact = contacts[0]

            # Mark as calling
            self.db.table("campaign_contacts").update(
                {"status": "calling", "attempts": contact["attempts"] + 1}
            ).eq("id", contact["id"]).execute()

            # Create call record
            call_result = (
                self.db.table("calls")
                .insert(
                    {
                        "account_id": campaign["account_id"],
                        "employee_id": campaign["employee_id"],
                        "phone_number": contact["phone_number"],
                        "direction": "outbound",
                        "status": "pending",
                        "campaign_id": campaign["id"],
                    }
                )
                .select("id")
                .single()
                .execute()
            )

            call_id = call_result.data["id"] if call_result.data else None

            if call_id:
                try:
                    await self.tel.make_call(
                        phone_number=contact["phone_number"],
                        employee_id=campaign["employee_id"],
                        call_id=call_id,
                        account_id=campaign["account_id"],
                    )

                    # Update contact with call reference
                    self.db.table("campaign_contacts").update(
                        {"call_id": call_id}
                    ).eq("id", contact["id"]).execute()

                    # Update campaign stats
                    self.db.table("campaigns").update(
                        {"completed_calls": campaign["completed_calls"] + 1}
                    ).eq("id", campaign["id"]).execute()

                except Exception as e:
                    logger.error(
                        "campaign_call_failed",
                        campaign_id=campaign["id"],
                        contact_id=contact["id"],
                        error=str(e),
                    )

                    # Check if should retry
                    max_retries = campaign.get("max_retries", 3)
                    retry_schedule = campaign.get("retry_schedule", [30, 120, 1440])

                    if contact["attempts"] < max_retries:
                        retry_minutes = retry_schedule[
                            min(contact["attempts"], len(retry_schedule) - 1)
                        ]
                        next_retry = datetime.now(IST) + timedelta(
                            minutes=retry_minutes
                        )
                        self.db.table("campaign_contacts").update(
                            {
                                "status": "pending",
                                "next_retry_at": next_retry.isoformat(),
                            }
                        ).eq("id", contact["id"]).execute()
                    else:
                        self.db.table("campaign_contacts").update(
                            {"status": "failed"}
                        ).eq("id", contact["id"]).execute()

            # Small delay between calls to avoid overwhelming telephony
            await asyncio.sleep(2)
