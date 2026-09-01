# %%
"""FastAPI application entrypoint."""

import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.passages import router as passages_router
from app.config import settings
from app.database.supabase import close_http_client


# %%
@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    yield
    # Supabase clients borrow a shared connection pool that is opened lazily on
    # the first request; hand its sockets back on the way out.
    await close_http_client()


# %%
app = FastAPI(title="Document Copilot API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(passages_router)


# %%
@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# %%
# `__name__` is also "__main__" inside a Jupyter kernel, so check for ipykernel
# too — otherwise running this cell blocks the kernel on a live server.
if __name__ == "__main__" and "ipykernel" not in sys.modules:
    import uvicorn

    uvicorn.run("app.main:app", reload=True)
