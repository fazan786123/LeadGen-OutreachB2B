from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os

from database import Base, engine
from routers import leads, campaigns, outreach, dashboard, preview

Base.metadata.create_all(bind=engine)

app = FastAPI(title="LeadGen OutreachB2B", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(leads.router)
app.include_router(campaigns.router)
app.include_router(outreach.router)
app.include_router(dashboard.router)
app.include_router(preview.router)

# Serve frontend
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=os.path.join(frontend_path, "static")), name="static")

    @app.get("/")
    def serve_index():
        return FileResponse(os.path.join(frontend_path, "index.html"))

    @app.get("/{page}.html")
    def serve_page(page: str):
        filepath = os.path.join(frontend_path, f"{page}.html")
        if os.path.exists(filepath):
            return FileResponse(filepath)
        return FileResponse(os.path.join(frontend_path, "index.html"))
