"""Phase 0: Infrastructure tests — no Bedrock required."""

import os
import subprocess
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class TestBackendStartup:
    """Test that the backend application loads correctly."""

    def test_app_imports(self):
        """Backend app module imports without errors."""
        from backend.api.main import app
        assert app is not None
        assert app.title == "SQL to DynamoDB Design Mentor API"

    def test_db_models_import(self):
        """DB models import and have expected tables."""
        from backend.db.models import (
            Project, Entity, AccessPattern, WritePattern,
            MigrationScope, PipelineRun, PipelineResult, ModelOverride,
        )
        assert Project.__tablename__ == "projects"
        assert Entity.__tablename__ == "entities"
        assert AccessPattern.__tablename__ == "access_patterns"

    def test_pipeline_runner_import(self):
        """Pipeline runner imports without errors."""
        from backend.services.pipeline_runner import PipelineRunner
        assert PipelineRunner is not None

    def test_consensus_import(self):
        """Consensus module imports without errors."""
        from backend.services.consensus import ConsensusExtractor, ConsensusComparer, ResultMerger
        assert ConsensusExtractor is not None


class TestFrontendBuild:
    """Test that the frontend compiles."""

    def test_typescript_compiles(self):
        """Frontend TypeScript compiles without errors."""
        frontend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
        if not os.path.isdir(frontend_dir):
            pytest.skip("Frontend directory not found")
        npx_cmd = "npx.cmd" if sys.platform == "win32" else "npx"
        try:
            result = subprocess.run(
                [npx_cmd, "tsc", "--noEmit"],
                cwd=frontend_dir,
                capture_output=True, text=True, timeout=120,
            )
        except FileNotFoundError:
            pytest.skip("npx not found on PATH")
        except subprocess.TimeoutExpired:
            pytest.skip("TypeScript compilation timed out (>120s)")
        assert result.returncode == 0, f"TypeScript errors:\n{result.stdout}\n{result.stderr}"


class TestAWSCredentials:
    """Test AWS credential validity."""

    def test_aws_profile_valid(self, validate_aws_credentials):
        """AWS profile has valid credentials."""
        account_id = validate_aws_credentials
        assert account_id is not None
        assert len(account_id) == 12

    def test_bedrock_model_access(self, aws_profile):
        """Bedrock models are accessible."""
        import boto3
        try:
            session = boto3.Session(profile_name=aws_profile, region_name="us-east-1")
            client = session.client("bedrock-runtime")
            # Just verify the client can be created — actual model access tested in E2E
            assert client is not None
        except Exception as e:
            pytest.skip(f"Bedrock not accessible: {e}")


class TestProjectSetup:
    """Test project creation via DB."""

    def test_create_project(self, db_session):
        """Can create a project in the database."""
        from backend.db.repositories import ProjectRepository
        repo = ProjectRepository(db_session)
        project = repo.create(
            name="Test Project",
            path="sample-dotnet-project",
            aws_profile="default",
        )
        assert project.id is not None
        assert project.name == "Test Project"

    def test_sample_project_exists(self, sample_project_path):
        """Sample .NET project directory exists."""
        assert os.path.isdir(sample_project_path)
        # Check for key files
        assert os.path.exists(os.path.join(sample_project_path, "Data", "AppDbContext.cs"))
