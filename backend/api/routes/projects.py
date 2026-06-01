from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.db.repositories import ProjectRepository
from backend.api.schemas import ProjectCreate, ProjectUpdate, ProjectResponse
import os
from pathlib import Path
import configparser

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/utils/aws-profiles", response_model=list[str])
def list_aws_profiles():
    """Parse ~/.aws/credentials and ~/.aws/config to return available profile names."""
    profiles = set()
    home = Path.home()
    # Parse credentials file
    creds_file = home / ".aws" / "credentials"
    if creds_file.exists():
        parser = configparser.ConfigParser()
        parser.read(str(creds_file), encoding="utf-8")
        profiles.update(parser.sections())
    # Parse config file (profiles are prefixed with "profile ")
    config_file = home / ".aws" / "config"
    if config_file.exists():
        parser = configparser.ConfigParser()
        parser.read(str(config_file), encoding="utf-8")
        for section in parser.sections():
            name = section.replace("profile ", "") if section.startswith("profile ") else section
            profiles.add(name)
    return sorted(profiles)


@router.get("/utils/browse-dirs")
def browse_directories(path: str = Query("."), include_files: str = Query("")):
    """List subdirectories (and optionally files) of the given path for browsing.
    include_files: comma-separated extensions like '.sql,.txt' to also list files.
    Browsing is restricted to safe directories only."""

    # Security: Reject path traversal sequences before any filesystem operation
    if ".." in path or "\0" in path or "~" in path:
        raise HTTPException(status_code=400, detail="Invalid path characters")

    # Security: Use os.path.realpath on a hardcoded base to prevent taint propagation
    # The path must be an absolute path to an existing directory
    safe_path = os.path.realpath(os.path.abspath(path))

    # Verify the safe_path is under an allowed root
    home_dir = os.path.realpath(str(Path.home()))
    import sys
    allowed_roots = [home_dir]
    if sys.platform == "win32":
        # Allow drive roots on Windows
        if len(safe_path) >= 3 and safe_path[1] == ':' and safe_path[2] == os.sep:
            allowed_roots.append(safe_path[:3])  # e.g., "C:\"

    is_allowed = any(safe_path.startswith(root) for root in allowed_roots)
    if not is_allowed:
        raise HTTPException(status_code=403, detail="Access denied: path outside allowed directories")

    try:
        if not os.path.exists(safe_path) or not os.path.isdir(safe_path):
            parent = os.path.dirname(safe_path)
            return {"current": safe_path, "parent": parent, "dirs": [], "files": []}

        dirs = []
        files = []
        file_exts = set(e.strip().lower() for e in include_files.split(',') if e.strip()) if include_files else set()
        skip = {'node_modules', 'bin', 'obj', '__pycache__', '.git', '.vs', '.vscode'}
        try:
            for entry_name in sorted(os.listdir(safe_path)):
                if entry_name.startswith('.'):
                    continue
                entry_path = os.path.join(safe_path, entry_name)
                if os.path.isdir(entry_path) and entry_name not in skip:
                    dirs.append({"name": entry_name, "path": entry_path})
                elif os.path.isfile(entry_path) and file_exts:
                    _, ext = os.path.splitext(entry_name)
                    if ext.lower() in file_exts:
                        files.append({"name": entry_name, "path": entry_path})
        except PermissionError:
            pass
        parent = os.path.dirname(safe_path)
        return {"current": safe_path, "parent": parent, "dirs": dirs, "files": files}
    except HTTPException:
        raise
    except Exception as e:
        return {"current": path, "parent": ".", "dirs": [], "files": [], "error": str(e)}


@router.post("/", response_model=ProjectResponse)
def create_project(req: ProjectCreate, db: Session = Depends(get_db)):
    repo = ProjectRepository(db)
    return repo.create(name=req.name, path=req.path, aws_profile=req.aws_profile, design_priority=req.design_priority, schema_path=req.schema_path)


@router.post("/utils/validate-bedrock")
def validate_bedrock_access(profile: str = Query(...), region: str = Query("us-east-1")):
    """Validate that the AWS profile has access to the required Bedrock models.
    Returns status for each model (Sonnet and Opus)."""
    import boto3
    from pipeline import SONNET_MODEL_ID, OPUS_MODEL_ID

    results = {
        "profile": profile,
        "region": region,
        "credentials_valid": False,
        "models": {
            "sonnet": {"model_id": SONNET_MODEL_ID, "accessible": False, "used_by": "Extractor, Metrics Analyzer", "required": True, "error": None},
            "opus": {"model_id": OPUS_MODEL_ID, "accessible": False, "used_by": "Architect, Validator", "required": False, "error": None},
        },
        "ready": False,
        "instructions": [],
    }

    # Check credentials
    try:
        session = boto3.Session(profile_name=profile, region_name=region)
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        results["credentials_valid"] = True
        results["account_id"] = identity.get("Account", "unknown")
    except Exception as e:
        results["models"]["sonnet"]["error"] = f"Credentials error: {str(e)}"
        results["models"]["opus"]["error"] = f"Credentials error: {str(e)}"
        results["instructions"].append(f"Run 'aws sso login --profile {profile}' to refresh your credentials")
        return results

    # Check each model
    bedrock = session.client("bedrock-runtime", region_name=region)
    for key, model_info in results["models"].items():
        model_id = model_info["model_id"]
        try:
            # Send a minimal invoke to test access (will fail fast if no access)
            bedrock.invoke_model(
                modelId=model_id,
                contentType="application/json",
                body='{"anthropic_version":"bedrock-2023-05-31","max_tokens":1,"messages":[{"role":"user","content":"hi"}]}'
            )
            model_info["accessible"] = True
        except bedrock.exceptions.AccessDeniedException:
            model_info["error"] = "Access denied — model not enabled"
            model_info["accessible"] = False
        except bedrock.exceptions.ValidationException as e:
            if "model identifier is invalid" in str(e).lower():
                model_info["error"] = "Model not available in this region"
            else:
                model_info["accessible"] = True  # Other validation errors mean we have access
        except Exception as e:
            err_str = str(e).lower()
            if "access" in err_str or "denied" in err_str or "not authorized" in err_str:
                model_info["error"] = "Access denied — model not enabled"
            else:
                model_info["accessible"] = True  # Connection worked, other error

    # Build instructions
    sonnet_ok = results["models"]["sonnet"]["accessible"]
    opus_ok = results["models"]["opus"]["accessible"]

    if not sonnet_ok:
        results["instructions"].append(
            f"Enable Claude Sonnet 4 in Bedrock Model Access: AWS Console → Bedrock → Model access → Request access for '{SONNET_MODEL_ID}'"
        )
    if not opus_ok:
        results["instructions"].append(
            f"Enable Claude Opus 4.6 in Bedrock Model Access: AWS Console → Bedrock → Model access → Request access for '{OPUS_MODEL_ID}'. "
            f"(Optional — if not available, Sonnet will be used for all agents)"
        )

    results["ready"] = sonnet_ok  # Sonnet is required, Opus is optional
    return results


@router.get("/", response_model=list[ProjectResponse])
def list_projects(db: Session = Depends(get_db)):
    repo = ProjectRepository(db)
    return repo.get_all()


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: int, db: Session = Depends(get_db)):
    repo = ProjectRepository(db)
    project = repo.get_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(project_id: int, req: ProjectUpdate, db: Session = Depends(get_db)):
    repo = ProjectRepository(db)
    project = repo.update(project_id, **req.model_dump(exclude_unset=True))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    repo = ProjectRepository(db)
    if not repo.delete(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"detail": "Deleted"}
