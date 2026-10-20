"""FastAPI application shell for Setu Supply Track 2."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from setu.api.track2 import router as track2_router

app = FastAPI(
    title="Setu Supply - Track 2 (Forecasting & GIS Planning)",
    version="0.1.0",
    description="Statistically grounded demand forecasting with honest uncertainty, FEFO stock projection, and HiGHS MILP GIS distribution planning.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(track2_router)


@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok", "service": "setu-supply-track2"}
