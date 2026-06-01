from sqlalchemy.orm import Session
from backend.db.models import PipelineRun, PipelineResult
from datetime import datetime, timezone


class PipelineRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_run(self, project_id: int, phases_config: dict) -> PipelineRun:
        total = sum(1 for v in phases_config.values() if v)
        run = PipelineRun(
            project_id=project_id,
            status="pending",
            phases_config=phases_config,
            total_phases=total,
            started_at=datetime.now(timezone.utc)
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def get_run(self, run_id: int) -> PipelineRun | None:
        return self.db.query(PipelineRun).filter(PipelineRun.id == run_id).first()

    def get_runs_by_project(self, project_id: int) -> list[PipelineRun]:
        return (self.db.query(PipelineRun)
                .filter(PipelineRun.project_id == project_id)
                .order_by(PipelineRun.started_at.desc())
                .all())

    def update_run_status(self, run_id: int, status: str, current_phase: int = None, error_message: str = None) -> PipelineRun | None:
        run = self.get_run(run_id)
        if not run:
            return None
        run.status = status
        if current_phase is not None:
            run.current_phase = current_phase
        if error_message:
            run.error_message = error_message
        if status in ("completed", "failed"):
            run.completed_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(run)
        return run

    def save_result(self, run_id: int, phase: int, phase_name: str, output_type: str, content: str) -> PipelineResult:
        result = PipelineResult(
            run_id=run_id,
            phase=phase,
            phase_name=phase_name,
            output_type=output_type,
            content=content
        )
        self.db.add(result)
        self.db.commit()
        self.db.refresh(result)
        return result

    def get_results(self, run_id: int) -> list[PipelineResult]:
        return (self.db.query(PipelineResult)
                .filter(PipelineResult.run_id == run_id)
                .order_by(PipelineResult.phase)
                .all())

    def get_latest_result(self, project_id: int, output_type: str) -> PipelineResult | None:
        return (self.db.query(PipelineResult)
                .join(PipelineRun)
                .filter(PipelineRun.project_id == project_id, PipelineResult.output_type == output_type)
                .order_by(PipelineResult.created_at.desc())
                .first())
