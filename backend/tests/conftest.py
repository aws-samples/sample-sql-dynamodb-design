"""Shared test fixtures for SQL to DynamoDB Design Mentor integration tests."""

import json
import os
import sys
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.db.models import Base
from backend.db.database import get_db


# --- Configuration ---

SAMPLE_PROJECT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "sample-dotnet-project")
BASELINES_DIR = os.path.join(os.path.dirname(__file__), "baselines")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "output")
ROSLYN_ANALYZER_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "tools", "analyzer", "SqlToDynamoDbDesignMentorAnalyzer.csproj")


@pytest.fixture(scope="session")
def sample_project_path():
    """Path to the sample .NET project for testing."""
    assert os.path.isdir(SAMPLE_PROJECT_PATH), f"Sample project not found: {SAMPLE_PROJECT_PATH}"
    return SAMPLE_PROJECT_PATH


@pytest.fixture(scope="session")
def roslyn_analyzer_path():
    """Path to the Roslyn analyzer project."""
    return ROSLYN_ANALYZER_PATH


@pytest.fixture(scope="session")
def baselines_dir():
    """Path to the baselines directory."""
    os.makedirs(BASELINES_DIR, exist_ok=True)
    return BASELINES_DIR


@pytest.fixture(scope="session")
def output_dir():
    """Path to the pipeline output directory."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    return OUTPUT_DIR


@pytest.fixture(scope="session")
def db_engine():
    """Create a test database engine."""
    test_db_path = os.path.join(os.path.dirname(__file__), "..", "..", "test_app.db")
    engine = create_engine(f"sqlite:///{test_db_path}", echo=False)
    Base.metadata.create_all(engine)
    yield engine
    # Cleanup — dispose engine first to release file lock
    engine.dispose()
    try:
        if os.path.exists(test_db_path):
            os.remove(test_db_path)
    except PermissionError:
        pass  # File still locked on Windows — will be cleaned up next run


@pytest.fixture
def db_session(db_engine):
    """Create a fresh DB session for each test."""
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture(scope="session")
def aws_profile():
    """Get the AWS profile for Bedrock access. Skip tests if not configured."""
    profile = os.environ.get("AWS_PROFILE", "default")
    return profile


@pytest.fixture(scope="session")
def validate_aws_credentials(aws_profile):
    """Validate AWS credentials before running Bedrock tests."""
    import boto3
    try:
        session = boto3.Session(profile_name=aws_profile)
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        return identity["Account"]
    except Exception as e:
        pytest.skip(f"AWS credentials not valid for profile '{aws_profile}': {e}")


def load_baseline(baselines_dir, name):
    """Load a baseline JSON file. Returns None if not found."""
    path = os.path.join(baselines_dir, f"{name}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_baseline(baselines_dir, name, data):
    """Save a baseline JSON file."""
    os.makedirs(baselines_dir, exist_ok=True)
    path = os.path.join(baselines_dir, f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
