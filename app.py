"""Public portfolio sandbox. All amounts and transactions are simulations."""

import os
import re
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from starlette.exceptions import HTTPException as StarletteHTTPException

app = FastAPI(
    title="Payments Lab", docs_url="/api/docs", openapi_url="/api/openapi.json"
)
PUBLIC = Path(__file__).parent / "web"
app.mount("/assets", StaticFiles(directory=PUBLIC), name="assets")


class OrderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: int = Field(strict=True, gt=0, le=100_000_000)
    currency: Literal["INR", "USD", "EUR", "GBP"] = "INR"
    outcome: Literal["success", "failure"] = "success"


class PaymentInput(OrderInput):
    order_id: str = Field(min_length=1, max_length=128)


@lru_cache(maxsize=1)
def database():
    uri = os.getenv("MONGO_URI")
    if not uri:
        raise HTTPException(503, "Cloud database is not configured yet")
    db = MongoClient(
        uri,
        tz_aware=True,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=8000,
        maxPoolSize=10,
    )[os.getenv("MONGO_DATABASE", "payments_live_app")]
    db.transactions.create_index([("session", 1), ("key", 1)], unique=True)
    db.orders.create_index([("session", 1), ("created_at", -1)])
    for name in ("transactions", "orders", "limits"):
        db[name].create_index("expires_at", expireAfterSeconds=0)
    return db


def session(request: Request, response: Response):
    value = request.cookies.get("payments_session", "")
    if not re.fullmatch(r"[a-f0-9]{64}", value):
        value = secrets.token_hex(32)
        response.set_cookie(
            "payments_session",
            value,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            max_age=604800,
        )
    return value


def guard(request: Request, sid: str):
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Use the app on this site to submit requests")
    bucket = f"{sid}:{int(time.time() // 60)}"
    try:
        row = database().limits.find_one_and_update(
            {"_id": bucket},
            {
                "$inc": {"count": 1},
                "$setOnInsert": {
                    "expires_at": datetime.now(timezone.utc) + timedelta(minutes=2)
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        row = database().limits.find_one_and_update(
            {"_id": bucket},
            {"$inc": {"count": 1}},
            return_document=ReturnDocument.AFTER,
        )
    if row["count"] > 30:
        raise HTTPException(429, "Please wait a minute before submitting more requests")


def payment_result(payload: PaymentInput, key: str, sid: str):
    """Atomic insert-once ledger; scoped keys cannot expose other visitors' payments."""
    record = {
        "session": sid,
        "key": key,
        "payload": payload.model_dump(),
        "transaction_id": str(uuid.uuid4()),
        "status": "paid" if payload.outcome == "success" else "failed",
        "expires_at": datetime.now(timezone.utc) + timedelta(days=7),
    }
    query = {"session": sid, "key": key}
    try:
        original = database().transactions.find_one_and_update(
            query,
            {"$setOnInsert": record},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        original = database().transactions.find_one(query)
    if original["payload"] != payload.model_dump():
        raise HTTPException(
            409, "Idempotency key already used with a different payload"
        )
    return {k: original[k] for k in ("transaction_id", "status", "payload")}


def order_public(row):
    return {
        "id": row["_id"],
        **{
            k: row[k]
            for k in ("amount", "currency", "status", "transaction_id", "created_at")
        },
    }


def settle(row, sid):
    result = payment_result(
        PaymentInput(order_id=row["_id"], **row["request"]), "order:" + row["_id"], sid
    )
    database().orders.update_one(
        {"_id": row["_id"], "session": sid, "status": "pending"},
        {
            "$set": {
                "status": result["status"],
                "transaction_id": result["transaction_id"],
            }
        },
    )
    return database().orders.find_one({"_id": row["_id"], "session": sid})


@app.get("/")
def home():
    return FileResponse(PUBLIC / "index.html")


@app.get("/api/health")
def health():
    try:
        database().command("ping")
    except (PyMongoError, HTTPException):
        return JSONResponse(
            {"status": "unavailable", "simulation": True}, status_code=503
        )
    return {"status": "ready", "simulation": True, "storage": "MongoDB"}


@app.get("/api/orders")
def orders(sid=Depends(session)):
    rows = database().orders.find({"session": sid}).sort("created_at", -1).limit(50)
    return {"orders": [order_public(row) for row in rows], "retention_days": 7}


@app.post("/api/orders", status_code=201)
def create_order(payload: OrderInput, request: Request, sid=Depends(session)):
    guard(request, sid)
    row = {
        "_id": str(uuid.uuid4()),
        "session": sid,
        "request": payload.model_dump(),
        "amount": payload.amount,
        "currency": payload.currency,
        "status": "pending",
        "transaction_id": None,
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(days=7),
    }
    database().orders.insert_one(row)
    return order_public(settle(row, sid))


@app.get("/api/orders/{order_id}")
def get_order(order_id: str, sid=Depends(session)):
    row = database().orders.find_one({"_id": order_id, "session": sid})
    if not row:
        raise HTTPException(404, "Order not found in your session")
    # A committed payment with an interrupted order update recovers on the next read.
    if row["status"] == "pending":
        row = settle(row, sid)
    return order_public(row)


@app.post("/api/payments")
def pay(
    payload: PaymentInput,
    request: Request,
    sid=Depends(session),
    idempotency_key: str = Header(min_length=1, max_length=128),
):
    guard(request, sid)
    return payment_result(payload, idempotency_key, sid)


@app.exception_handler(StarletteHTTPException)
async def http_error(request, exc):
    return JSONResponse(
        {"error": {"code": str(exc.status_code), "message": str(exc.detail)}},
        status_code=exc.status_code,
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse(
        {
            "error": {
                "code": "validation_error",
                "message": "Check amount, currency, and outcome",
            }
        },
        status_code=422,
    )


@app.exception_handler(PyMongoError)
async def storage_error(request, exc):
    return JSONResponse(
        {
            "error": {
                "code": "storage_unavailable",
                "message": "Database unavailable. Retry shortly.",
            }
        },
        status_code=503,
    )
