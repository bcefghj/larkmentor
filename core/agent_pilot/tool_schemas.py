"""OpenAI function-calling tool definitions for Agent-Pilot."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "im.fetch_thread",
            "description": "Fetch recent messages from an IM chat thread",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "The chat/group ID to fetch from"},
                    "limit": {"type": "integer", "description": "Max messages to fetch", "default": 20},
                },
                "required": ["chat_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "im.send",
            "description": "Send a text message to an IM chat",
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "The chat/group ID to send to"},
                    "text": {"type": "string", "description": "Message text to send"},
                },
                "required": ["chat_id", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "doc.create",
            "description": "Create a new Feishu document",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Document title"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "doc.append",
            "description": "Append markdown content to an existing Feishu document",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_token": {"type": "string", "description": "Token of the target document"},
                    "markdown": {"type": "string", "description": "Markdown content to append"},
                },
                "required": ["doc_token", "markdown"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "canvas.create",
            "description": "Create a new whiteboard canvas",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Canvas title"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "canvas.add_shape",
            "description": "Add a shape to an existing canvas",
            "parameters": {
                "type": "object",
                "properties": {
                    "canvas_id": {"type": "string", "description": "Target canvas ID"},
                    "shape_type": {"type": "string", "description": "Shape type (rect, node, arrow, frame, image, table, sticky)"},
                    "text": {"type": "string", "description": "Text content inside the shape"},
                    "x": {"type": "number", "description": "X position", "default": 100},
                    "y": {"type": "number", "description": "Y position", "default": 100},
                    "w": {"type": "number", "description": "Width", "default": 200},
                    "h": {"type": "number", "description": "Height", "default": 80},
                },
                "required": ["canvas_id", "shape_type", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "slide.generate",
            "description": "Generate a slide deck from a title and outline",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Slide deck title"},
                    "outline": {
                        "description": "Slide outline as a list of page objects or a newline-separated string",
                        "oneOf": [
                            {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "title": {"type": "string"},
                                        "bullets": {"type": "array", "items": {"type": "string"}},
                                    },
                                },
                            },
                            {"type": "string"},
                        ],
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "slide.rehearse",
            "description": "Generate speaker notes for a slide deck",
            "parameters": {
                "type": "object",
                "properties": {
                    "slide_id": {"type": "string", "description": "ID of the slide deck to rehearse"},
                },
                "required": ["slide_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "voice.transcribe",
            "description": "Transcribe audio to text via ASR or return inline text",
            "parameters": {
                "type": "object",
                "properties": {
                    "audio_url": {"type": "string", "description": "URL of the audio file"},
                    "file_key": {"type": "string", "description": "Feishu file key or minute token"},
                    "text": {"type": "string", "description": "Pre-existing text (skip ASR if provided)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "archive.bundle",
            "description": "Bundle all artifacts from the current run into a manifest and summary document",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mentor.clarify",
            "description": "Ask clarifying questions when the user intent is ambiguous",
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {"type": "string", "description": "The ambiguous user intent to clarify"},
                },
                "required": ["intent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mentor.summarize",
            "description": "Summarize a list of messages into key decisions and consensus points",
            "parameters": {
                "type": "object",
                "properties": {
                    "messages": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "sender": {"type": "string"},
                                "text": {"type": "string"},
                            },
                        },
                        "description": "Messages to summarize",
                    },
                },
                "required": ["messages"],
            },
        },
    },
]


def get_tool_definitions() -> List[Dict[str, Any]]:
    return TOOL_DEFINITIONS


def get_tool_by_name(name: str) -> Optional[Dict[str, Any]]:
    for t in TOOL_DEFINITIONS:
        if t["function"]["name"] == name:
            return t
    return None
