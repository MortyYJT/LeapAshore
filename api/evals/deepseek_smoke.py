from __future__ import annotations

import argparse
import asyncio
import json
from time import perf_counter

from app.services.deepseek_advisor import stream_deepseek


async def run() -> dict[str, object]:
    context = {
        "profile": {"school_tier": "双非", "undergraduate_major": "软件工程", "gpa_percent": 82, "target_field": "计算机与数据"},
        "recommendations": [], "application_portfolio": [], "roadmap_tasks": [], "recent_messages": [],
        "user_message": "请用两句话说明我下一步应该补充哪些申请信息。",
    }
    started = perf_counter()
    first_delta_ms = None
    output = []
    async for kind, value in stream_deepseek(context):
        if kind == "delta":
            if first_delta_ms is None:
                first_delta_ms = round((perf_counter() - started) * 1000)
            output.append(str(value))
    total_ms = round((perf_counter() - started) * 1000)
    if not output:
        raise AssertionError("DeepSeek returned no text")
    return {
        "first_delta_ms": first_delta_ms,
        "total_ms": total_ms,
        "target_first_delta_ms": 3000,
        "target_total_ms": 8000,
        "text": "".join(output),
    }


if __name__ == "__main__":
    argparse.ArgumentParser(description="Run an opt-in real DeepSeek latency smoke test.").parse_args()
    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2))
