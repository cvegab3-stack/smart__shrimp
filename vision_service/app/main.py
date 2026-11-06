"""Aplicación FastAPI privada de visión artificial."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.frame_routes import router as frame_router
from app.api.http_routes import router as http_router
from app.pipeline.frame_pipeline import frame_pipeline


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Precarga el detector para que el primer fotograma no supere el tiempo límite de Django."""
    frame_pipeline.detector.warmup()
    yield


app = FastAPI(title="SMART SHRIMP Vision Service", version="1.0.0", lifespan=lifespan)
app.include_router(frame_router)
app.include_router(http_router)
