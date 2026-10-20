"""HTTP API and static frontend."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .model import project
from .schemas import Plan, default_plan
from .storage import PlanStore

STATIC_DIR = Path(__file__).parent / "static"


def create_app(db_path: str | Path | None = None) -> FastAPI:
    store = PlanStore(db_path or os.environ.get("TUTOR_DB_PATH", "data/tutor.db"))
    app = FastAPI(title="Tutor Income Planner")

    def current_plan() -> tuple[Plan, str | None]:
        saved = store.load()
        if saved is None:
            return default_plan(date.today()), None
        return saved

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/plan")
    def get_plan() -> dict:
        plan, saved_at = current_plan()
        return {"plan": plan.model_dump(mode="json"), "saved_at": saved_at}

    @app.put("/api/plan")
    def put_plan(plan: Plan) -> dict:
        saved_at = store.save(plan)
        return {
            "plan": plan.model_dump(mode="json"),
            "saved_at": saved_at,
            "projection": project(plan),
        }

    @app.get("/api/projection")
    def get_projection() -> dict:
        plan, _ = current_plan()
        return project(plan)

    @app.post("/api/projection")
    def preview_projection(plan: Plan) -> dict:
        """Project a plan without saving it."""
        return project(plan)

    @app.get("/api/export")
    def export_plan() -> JSONResponse:
        plan, _ = current_plan()
        filename = f"tutor-plan-{date.today().isoformat()}.json"
        return JSONResponse(
            plan.model_dump(mode="json"),
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
