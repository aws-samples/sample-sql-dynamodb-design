from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import json
import asyncio
import logging
import os

from backend.db.database import get_db, SessionLocal
from backend.db.repositories import PipelineRepository, ScopeRepository, EntityRepository, PatternRepository
from backend.api.schemas import PipelineRunRequest, PipelineRunResponse, PipelineResultResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects/{project_id}/pipeline", tags=["pipeline"])


@router.post("/extract")
async def run_extraction(project_id: int):
    """SSE endpoint that runs only the Extractor agent and syncs results to DB."""
    logger.info("POST /extract called for project_id=%s", project_id)

    async def event_generator():
        db = SessionLocal()
        runner = None
        try:
            from backend.db.repositories import ProjectRepository
            project_repo = ProjectRepository(db)
            project = project_repo.get_by_id(project_id)
            if not project:
                yield f"data: {json.dumps({'status': 'failed', 'error': 'Project not found'})}\n\n"
                return

            yield f"data: {json.dumps({'status': 'running', 'message': '🔍 Starting extraction...'})}\n\n"

            pipeline_repo = PipelineRepository(db)
            run = pipeline_repo.create_run(project_id=project_id, phases_config={"extract": True})

            from backend.services.pipeline_runner import PipelineRunner

            # Use an asyncio.Queue to stream logs in real-time
            log_queue: asyncio.Queue = asyncio.Queue()

            def log_callback(msg):
                log_queue.put_nowait(msg)

            runner = PipelineRunner(db, project_id, run.id, log_callback=log_callback)

            yield f"data: {json.dumps({'status': 'running', 'message': '📂 Scanning .NET project for entities and access patterns...'})}\n\n"

            # Run extraction in a background thread
            extract_task = asyncio.get_event_loop().run_in_executor(None, runner.run_extract)

            # Stream logs as they arrive
            while True:
                # Check if extraction is done
                done_check = extract_task.done()
                # Drain all available log messages
                while not log_queue.empty():
                    try:
                        msg = log_queue.get_nowait()
                        yield f"data: {json.dumps({'message': msg})}\n\n"
                    except asyncio.QueueEmpty:
                        break
                if done_check:
                    # Drain any remaining messages
                    while not log_queue.empty():
                        try:
                            msg = log_queue.get_nowait()
                            yield f"data: {json.dumps({'message': msg})}\n\n"
                        except asyncio.QueueEmpty:
                            break
                    # Re-raise any exception from the extraction
                    extract_task.result()
                    break
                await asyncio.sleep(0.3)

            pipeline_repo.update_run_status(run.id, "completed")

            entity_repo = EntityRepository(db)
            pattern_repo = PatternRepository(db)
            entities = entity_repo.get_by_project(project_id)
            access_patterns = pattern_repo.get_access_patterns(project_id)
            write_patterns = pattern_repo.get_write_patterns(project_id)

            # Read consensus report for confidence data
            confidence_score = None
            rounds_executed = None
            try:
                consensus_result = pipeline_repo.get_latest_result(project_id, "consensus_report")
                if consensus_result and consensus_result.content:
                    report = json.loads(consensus_result.content)
                    confidence_score = report.get("confidence_score")
                    rounds_executed = report.get("rounds_executed")
            except Exception as e:
                logger.warning(
                    "Failed to load consensus report for project %s: %s", project_id, e
                )

            # Include log file path for download
            log_file = runner.get_log_file_path() if runner else None

            completion_data = {
                'status': 'completed',
                'message': f'✅ Extraction complete: {len(entities)} entities, {len(access_patterns)} access patterns, {len(write_patterns)} write patterns',
                'entities': len(entities),
                'access_patterns': len(access_patterns),
                'write_patterns': len(write_patterns),
            }
            if confidence_score is not None:
                completion_data['confidence_score'] = confidence_score
            if rounds_executed is not None:
                completion_data['rounds_executed'] = rounds_executed
            if log_file:
                completion_data['log_file'] = os.path.basename(log_file)

            yield f"data: {json.dumps(completion_data)}\n\n"

        except Exception as e:
            logger.error("Extraction failed for project %s: %s", project_id, e, exc_info=True)
            yield f"data: {json.dumps({'status': 'failed', 'error': str(e)})}\n\n"
        finally:
            if runner:
                runner.close_file_logger()
            db.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )


@router.post("/run", response_model=PipelineRunResponse)
def create_run(project_id: int, req: PipelineRunRequest, db: Session = Depends(get_db)):
    repo = PipelineRepository(db)
    phases = {
        "extract": req.extract,
        "model": req.model,
        "validate": req.validate_phase,
        "metrics": req.metrics
    }
    run = repo.create_run(project_id=project_id, phases_config=phases)
    return run



@router.get("/run/{run_id}", response_model=PipelineRunResponse)
def get_run(project_id: int, run_id: int, db: Session = Depends(get_db)):
    repo = PipelineRepository(db)
    run = repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/summary")
def get_pipeline_summary(project_id: int, db: Session = Depends(get_db)):
    """Aggregated summary endpoint — replaces 4 separate API calls on RunExtract page."""
    entity_repo = EntityRepository(db)
    pattern_repo = PatternRepository(db)
    pipeline_repo = PipelineRepository(db)

    entities = entity_repo.get_by_project(project_id)
    access_patterns = pattern_repo.get_access_patterns(project_id)
    write_patterns = pattern_repo.get_write_patterns(project_id)
    runs = pipeline_repo.get_runs_by_project(project_id)

    # Find last completed extract run
    last_extract_run = None
    for r in runs:
        if r.phases_config and r.phases_config.get("extract") and r.status == "completed":
            last_extract_run = r
            break

    # Read consensus report if available
    confidence_score = None
    rounds_executed = None
    try:
        consensus_result = pipeline_repo.get_latest_result(project_id, "consensus_report")
        if consensus_result and consensus_result.content:
            import json as _json
            report = _json.loads(consensus_result.content)
            confidence_score = report.get("confidence_score")
            rounds_executed = report.get("rounds_executed")
    except Exception:
        pass

    return {
        "entities": len(entities),
        "access_patterns": len(access_patterns),
        "write_patterns": len(write_patterns),
        "last_extract_completed_at": last_extract_run.completed_at.isoformat() if last_extract_run and last_extract_run.completed_at else None,
        "confidence_score": confidence_score,
        "rounds_executed": rounds_executed,
        "has_data": len(entities) > 0,
    }


@router.get("/run/{run_id}/results", response_model=list[PipelineResultResponse])
def get_run_results(project_id: int, run_id: int, db: Session = Depends(get_db)):
    repo = PipelineRepository(db)
    return repo.get_results(run_id)


@router.get("/runs", response_model=list[PipelineRunResponse])
def list_runs(project_id: int, db: Session = Depends(get_db)):
    repo = PipelineRepository(db)
    return repo.get_runs_by_project(project_id)


@router.get("/run/{run_id}/stream")
async def stream_pipeline(project_id: int, run_id: int):
    """SSE endpoint that executes the pipeline and streams progress."""
    logger.info("GET /run/%s/stream called for project_id=%s", run_id, project_id)

    async def event_generator():
        db = SessionLocal()
        runner = None
        try:
            pipeline_repo = PipelineRepository(db)
            scope_repo = ScopeRepository(db)
            entity_repo = EntityRepository(db)
            pattern_repo = PatternRepository(db)

            run = pipeline_repo.get_run(run_id)
            if not run:
                yield f"data: {json.dumps({'error': 'Run not found'})}\n\n"
                return

            phases = run.phases_config or {}
            pipeline_repo.update_run_status(run_id, "running")

            # Import agents lazily to avoid loading Bedrock on startup
            from backend.services.pipeline_runner import PipelineRunner

            # Use an asyncio.Queue to stream logs in real-time
            log_queue: asyncio.Queue = asyncio.Queue()

            def log_callback(msg):
                log_queue.put_nowait(msg)

            runner = PipelineRunner(db, project_id, run_id, log_callback=log_callback)

            phase_num = 0
            total = run.total_phases

            async def run_phase_with_streaming(phase_func):
                """Run a phase in a thread while streaming logs in real-time."""
                task = asyncio.get_event_loop().run_in_executor(None, phase_func)
                events = []
                while True:
                    done_check = task.done()
                    while not log_queue.empty():
                        try:
                            msg = log_queue.get_nowait()
                            events.append(f"data: {json.dumps({'message': msg})}\n\n")
                        except asyncio.QueueEmpty:
                            break
                    # Yield accumulated events
                    for evt in events:
                        yield evt
                    events.clear()
                    if done_check:
                        # Drain remaining
                        while not log_queue.empty():
                            try:
                                msg = log_queue.get_nowait()
                                yield f"data: {json.dumps({'message': msg})}\n\n"
                            except asyncio.QueueEmpty:
                                break
                        task.result()  # re-raise exceptions
                        break
                    await asyncio.sleep(0.3)

            # Phase 1: Extract
            if phases.get("extract"):
                phase_num += 1
                yield f"data: {json.dumps({'phase': 1, 'name': 'extract', 'status': 'running', 'progress': (phase_num - 0.5) / total, 'message': '🔍 Phase 1: Extracting access patterns from .NET codebase...'})}\n\n"
                async for evt in run_phase_with_streaming(runner.run_extract):
                    yield evt
                yield f"data: {json.dumps({'phase': 1, 'name': 'extract', 'status': 'complete', 'progress': phase_num / total})}\n\n"

            # Phase 2: Model
            if phases.get("model"):
                phase_num += 1
                yield f"data: {json.dumps({'phase': 2, 'name': 'model', 'status': 'running', 'progress': (phase_num - 0.5) / total, 'message': '🏗️ Phase 2: Designing DynamoDB single-table model with GSIs and C# queries...'})}\n\n"
                async for evt in run_phase_with_streaming(runner.run_model):
                    yield evt
                yield f"data: {json.dumps({'phase': 2, 'name': 'model', 'status': 'complete', 'progress': phase_num / total})}\n\n"

            # Phase 3: Validate
            if phases.get("validate"):
                phase_num += 1
                yield f"data: {json.dumps({'phase': 3, 'name': 'validate', 'status': 'running', 'progress': (phase_num - 0.5) / total, 'message': '✅ Phase 3: Validating access patterns against model — checking expressions, coverage, and correctness...'})}\n\n"
                async for evt in run_phase_with_streaming(runner.run_validate):
                    yield evt
                yield f"data: {json.dumps({'phase': 3, 'name': 'validate', 'status': 'complete', 'progress': phase_num / total})}\n\n"

            # Phase 4: Metrics
            if phases.get("metrics"):
                phase_num += 1
                yield f"data: {json.dumps({'phase': 4, 'name': 'metrics', 'status': 'running', 'progress': (phase_num - 0.5) / total, 'message': '📊 Phase 4: Calculating RCU/WCU capacity estimates and comparing modeling strategies...'})}\n\n"
                async for evt in run_phase_with_streaming(runner.run_metrics):
                    yield evt
                yield f"data: {json.dumps({'phase': 4, 'name': 'metrics', 'status': 'complete', 'progress': phase_num / total})}\n\n"

            pipeline_repo.update_run_status(run_id, "completed")

            # Include log file path for download
            log_file = runner.get_log_file_path() if runner else None
            completion_data = {'status': 'completed', 'progress': 1.0, 'message': '🎉 Pipeline complete! All phases finished successfully.'}
            if log_file:
                completion_data['log_file'] = os.path.basename(log_file)
            yield f"data: {json.dumps(completion_data)}\n\n"

        except Exception as e:
            logger.error("Pipeline stream failed for project %s, run %s: %s", project_id, run_id, e, exc_info=True)
            pipeline_repo.update_run_status(run_id, "failed", error_message=str(e))
            yield f"data: {json.dumps({'status': 'failed', 'error': str(e)})}\n\n"
        finally:
            if runner:
                runner.close_file_logger()
            db.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )


@router.get("/results/latest/{output_type}", response_model=PipelineResultResponse | None)
def get_latest_result(project_id: int, output_type: str, db: Session = Depends(get_db)):
    repo = PipelineRepository(db)
    result = repo.get_latest_result(project_id, output_type)
    if not result:
        raise HTTPException(status_code=404, detail=f"No result found for type: {output_type}")
    return result


@router.post("/import-files")
def import_files_from_disk(project_id: int, db: Session = Depends(get_db)):
    """Import pipeline output files from disk into the DB as pipeline results.
    No AWS credentials needed — just reads local files into DB."""
    repo = PipelineRepository(db)

    file_map = [
        (1, "extract", "access_patterns_md", os.path.join("output", "access_patterns.md")),
        (2, "model", "model_md", os.path.join("output", "dynamo_model.md")),
        (2, "model", "model_json", os.path.join("output", "dynamo_model.json")),
        (3, "validate", "validation_md", os.path.join("output", "validation_report.md")),
        (4, "metrics", "capacity_md", os.path.join("output", "capacity_analysis.md")),
    ]

    run = repo.create_run(project_id=project_id, phases_config={
        "extract": True, "model": True, "validate": True, "metrics": True
    })
    repo.update_run_status(run.id, "completed")

    imported = []
    for phase, phase_name, output_type, file_path in file_map:
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            if content.strip():
                repo.save_result(run.id, phase, phase_name, output_type, content)
                imported.append(output_type)

    # Sync entity/pattern data without importing pipeline.py (avoids AWS init)
    metrics_path = os.path.join("output", "entity_metrics.json")
    if os.path.exists(metrics_path):
        entity_repo = EntityRepository(db)
        pattern_repo = PatternRepository(db)
        with open(metrics_path, "r", encoding="utf-8", errors="replace") as f:
            metrics = json.load(f)

        entity_repo.delete_by_project(project_id)
        pattern_repo.delete_access_patterns(project_id)
        pattern_repo.delete_write_patterns(project_id)

        entities_data = []
        for name, data in metrics.get("entities", {}).items():
            entities_data.append({
                "name": name, "sql_table": data.get("sql_table"),
                "average_row_size_kb": data.get("average_row_size_kb", 0.5),
                "fields": data.get("fields"),
                "estimated_field_total_bytes": data.get("estimated_field_total_bytes"),
                "relationships_json": data.get("relationships"),
                "notes": data.get("notes"), "selected": True
            })
        if entities_data:
            entity_repo.bulk_create(project_id, entities_data)

        ap_data = []
        for ap_id, ap in metrics.get("access_patterns", {}).items():
            ap_data.append({
                "pattern_id": ap_id, "name": ap.get("name", ""),
                "operation": ap.get("operation", "READ"),
                "source_entities": ap.get("source_entities", []),
                "requests_per_hour": ap.get("requests_per_hour", 0),
                "avg_items_returned": ap.get("avg_items_returned", 1),
                "source_code": None, "notes": ap.get("notes"),
                "classification": "in_scope"
            })
        if ap_data:
            pattern_repo.bulk_create_access_patterns(project_id, ap_data)

        wp_data = []
        for wp_id, wp in metrics.get("write_patterns", {}).items():
            wp_data.append({
                "pattern_id": wp_id, "name": wp.get("name", ""),
                "operation": "WRITE",
                "target_entities": wp.get("target_entities", []),
                "requests_per_hour": wp.get("requests_per_hour", 0),
                "items_per_transaction": wp.get("items_per_transaction", 1),
                "source_code": None, "notes": wp.get("notes"),
                "classification": "in_scope"
            })
        if wp_data:
            pattern_repo.bulk_create_write_patterns(project_id, wp_data)

    return {"imported": imported, "run_id": run.id}


@router.get("/logs")
def list_log_files(project_id: int):
    """List available log files for download."""
    log_dir = "logs"
    if not os.path.isdir(log_dir):
        return {"logs": []}
    files = []
    for f in sorted(os.listdir(log_dir), reverse=True):
        if f.endswith(".log"):
            path = os.path.join(log_dir, f)
            files.append({
                "filename": f,
                "size_bytes": os.path.getsize(path),
                "modified": os.path.getmtime(path),
            })
    return {"logs": files}


@router.get("/logs/{filename}")
def download_log_file(project_id: int, filename: str):
    """Download a specific log file."""
    from fastapi.responses import FileResponse
    import re
    # Sanitize filename to prevent path traversal
    if not re.match(r'^run_\d{1,10}_\d{8}_\d{6}\.log$', filename):
        raise HTTPException(status_code=400, detail="Invalid log filename")
    log_path = os.path.join("logs", filename)
    # Verify resolved path is within logs directory (defense in depth)
    resolved = os.path.realpath(log_path)
    logs_dir = os.path.realpath("logs")
    if not resolved.startswith(logs_dir):
        raise HTTPException(status_code=403, detail="Access denied")
    if not os.path.exists(log_path):
        raise HTTPException(status_code=404, detail="Log file not found")
    return FileResponse(
        log_path,
        media_type="text/plain",
        filename=filename,
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

