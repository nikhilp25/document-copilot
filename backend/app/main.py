# %%
"""FastAPI application entrypoint."""

import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

# %%
app = FastAPI(title="Document Copilot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
