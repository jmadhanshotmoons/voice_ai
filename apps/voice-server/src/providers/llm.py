"""LLM provider using AWS Bedrock (Claude Haiku / Opus / DeepSeek).

Uses boto3 bedrock-runtime for inference. Supports:
- anthropic.claude-3-haiku-20240307-v1:0
- anthropic.claude-3-5-sonnet-20241022-v2:0
- anthropic.claude-opus-4-20250514-v1:0
- deepseek (if available in your region)

For voice calls, speed > quality. Claude Haiku is the best trade-off.
"""

import os
import json
import boto3
import structlog
from dataclasses import dataclass, field
from typing import Optional, AsyncIterator, List

logger = structlog.get_logger()


@dataclass
class ConversationMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    text: str
    finish_reason: str
    tool_calls: list = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


TOOLS = [
    {
        "name": "capture_field",
        "description": "Save information from the caller (name, budget, interest, etc.)",
        "input_schema": {
            "type": "object",
            "properties": {
                "field_name": {"type": "string", "description": "Name of the field"},
                "field_value": {"type": "string", "description": "Value captured"},
            },
            "required": ["field_name", "field_value"],
        },
    },
    {
        "name": "book_appointment",
        "description": "Book a calendar appointment when caller agrees to a date/time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "time": {"type": "string", "description": "HH:MM (24hr)"},
                "attendee_name": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["date", "time"],
        },
    },
    {
        "name": "send_whatsapp",
        "description": "Send a WhatsApp message to the caller.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "template": {
                    "type": "string",
                    "enum": ["confirmation", "brochure", "location"],
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "transfer_to_human",
        "description": "Transfer call to a human when caller asks or you cannot help.",
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    },
]


class BedrockLLM:
    """AWS Bedrock LLM provider -- Claude Haiku/Opus/DeepSeek."""

    def __init__(
        self,
        model_id: Optional[str] = None,
        region: Optional[str] = None,
    ):
        self.model_id = model_id or os.getenv(
            "AWS_BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0"
        )
        self.region = region or os.getenv("AWS_REGION", "us-east-1")
        self.client = boto3.client(
            "bedrock-runtime",
            region_name=self.region,
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", ""),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", ""),
        )

    async def generate(
        self,
        messages: List[ConversationMessage],
        tools_enabled: bool = True,
        max_tokens: int = 400,
    ) -> LLMResponse:
        """Generate a response using Bedrock Converse API."""
        import asyncio

        # Bedrock converse API uses a specific message format
        system_text = ""
        converse_messages = []

        for msg in messages:
            if msg.role == "system":
                system_text = msg.content
            else:
                converse_messages.append(
                    {"role": msg.role, "content": [{"text": msg.content}]}
                )

        # Ensure messages alternate user/assistant
        if not converse_messages:
            return LLMResponse(text="", finish_reason="error")

        kwargs = {
            "modelId": self.model_id,
            "messages": converse_messages,
            "inferenceConfig": {
                "maxTokens": max_tokens,
                "temperature": 0.7,
            },
        }

        if system_text:
            kwargs["system"] = [{"text": system_text}]

        if tools_enabled:
            kwargs["toolConfig"] = {
                "tools": [
                    {
                        "toolSpec": {
                            "name": t["name"],
                            "description": t["description"],
                            "inputSchema": {"json": t["input_schema"]},
                        }
                    }
                    for t in TOOLS
                ]
            }

        try:
            # Run sync boto3 call in executor to not block asyncio
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, lambda: self.client.converse(**kwargs)
            )

            output = response.get("output", {})
            message = output.get("message", {})
            content_blocks = message.get("content", [])
            stop_reason = response.get("stopReason", "end_turn")

            text_parts = []
            tool_calls = []

            for block in content_blocks:
                if "text" in block:
                    text_parts.append(block["text"])
                elif "toolUse" in block:
                    tu = block["toolUse"]
                    tool_calls.append(
                        {
                            "id": tu.get("toolUseId", ""),
                            "name": tu["name"],
                            "arguments": tu.get("input", {}),
                        }
                    )

            usage = response.get("usage", {})

            return LLMResponse(
                text=" ".join(text_parts),
                finish_reason=stop_reason,
                tool_calls=tool_calls,
                input_tokens=usage.get("inputTokens", 0),
                output_tokens=usage.get("outputTokens", 0),
            )

        except Exception as e:
            logger.error("bedrock_llm_error", error=str(e), model=self.model_id)
            return LLMResponse(
                text="I'm sorry, I didn't catch that. Could you repeat?",
                finish_reason="error",
            )

    # ───────────── Streaming (voice): tokens arrive while the model is still writing ─────────────

    def _converse_kwargs(self, messages: List[ConversationMessage], tools_enabled: bool, max_tokens: int) -> dict:
        system_text = ""
        converse_messages: list = []
        for msg in messages:
            if msg.role == "system":
                system_text = msg.content
                continue
            # Bedrock needs strictly alternating roles; merge neighbours of the same role
            if converse_messages and converse_messages[-1]["role"] == msg.role:
                converse_messages[-1]["content"][0]["text"] += "\n" + msg.content
            else:
                converse_messages.append({"role": msg.role, "content": [{"text": msg.content}]})
        if converse_messages and converse_messages[0]["role"] != "user":
            converse_messages.insert(0, {"role": "user", "content": [{"text": "(call connected)"}]})

        kwargs: dict = {
            "modelId": self.model_id,
            "messages": converse_messages,
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0.6},
        }
        if system_text:
            kwargs["system"] = [{"text": system_text}]
        if tools_enabled:
            kwargs["toolConfig"] = {
                "tools": [
                    {
                        "toolSpec": {
                            "name": t["name"],
                            "description": t["description"],
                            "inputSchema": {"json": t["input_schema"]},
                        }
                    }
                    for t in TOOLS
                ]
            }
        return kwargs

    async def stream(
        self,
        messages: List[ConversationMessage],
        tools_enabled: bool = True,
        max_tokens: int = 250,
    ):
        """Yield {"type": "text", "text"} deltas and {"type": "tool", "name", "arguments"}
        events as the model produces them, then a final {"type": "done"}."""
        import asyncio

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        kwargs = self._converse_kwargs(messages, tools_enabled, max_tokens)

        def worker():
            tool_blocks: dict = {}
            try:
                response = self.client.converse_stream(**kwargs)
                for event in response["stream"]:
                    if "contentBlockStart" in event:
                        start = event["contentBlockStart"].get("start", {})
                        if "toolUse" in start:
                            idx = event["contentBlockStart"]["contentBlockIndex"]
                            tool_blocks[idx] = {"name": start["toolUse"]["name"], "json": ""}
                    elif "contentBlockDelta" in event:
                        delta = event["contentBlockDelta"]["delta"]
                        idx = event["contentBlockDelta"]["contentBlockIndex"]
                        if "text" in delta:
                            loop.call_soon_threadsafe(queue.put_nowait, {"type": "text", "text": delta["text"]})
                        elif "toolUse" in delta and idx in tool_blocks:
                            tool_blocks[idx]["json"] += delta["toolUse"].get("input", "")
                    elif "contentBlockStop" in event:
                        idx = event["contentBlockStop"]["contentBlockIndex"]
                        tb = tool_blocks.pop(idx, None)
                        if tb:
                            try:
                                args = json.loads(tb["json"] or "{}")
                            except json.JSONDecodeError:
                                args = {}
                            loop.call_soon_threadsafe(
                                queue.put_nowait, {"type": "tool", "name": tb["name"], "arguments": args}
                            )
            except Exception as e:  # surface to the consumer
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "error": str(e)})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "done"})

        task = loop.run_in_executor(None, worker)
        try:
            while True:
                item = await queue.get()
                yield item
                if item["type"] == "done":
                    break
        finally:
            # If the consumer stops early (caller interrupted), let the worker finish on its own
            task.add_done_callback(lambda _f: None)
