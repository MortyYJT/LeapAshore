"""Vercel Services entrypoint; public traffic retains its /api path prefix."""

from fastapi import FastAPI

from app.main import app as offerpilot_api

app = FastAPI(title="OfferPilot Service Router")
app.mount("/api", offerpilot_api)

__all__ = ["app", "offerpilot_api"]
