import json
import logging
import time

from fastapi import APIRouter, FastAPI, Request
from sqlalchemy import text

from app import errors
from app.api.v1 import access, auth, bookings, inbox, meetings, org
from app.db import get_engine


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {"level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        data.update(getattr(record, "extra_fields", {}))
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)


def _configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)


log = logging.getLogger("relay.api")


def create_app() -> FastAPI:
    _configure_logging()
    app = FastAPI(
        title="Relay: Lab Resource Booking", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json"
    )
    errors.install(app)

    v1 = APIRouter(prefix="/api/v1")
    for r in (auth.router, org.router, bookings.router, access.router, inbox.router, meetings.router):
        v1.include_router(r)
    app.include_router(v1)

    @app.get("/health", tags=["ops"])
    def health():
        with get_engine().connect() as c:
            c.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        log.info(
            "request",
            extra={
                "extra_fields": {
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "ms": round((time.perf_counter() - started) * 1000, 1),
                }
            },
        )
        return response

    return app


app = create_app()
