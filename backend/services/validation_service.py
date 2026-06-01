import json
import logging
import os

import boto3
from sqlalchemy.orm import Session
from strands import Agent
from strands.models import BedrockModel

from backend.api.schemas import (
    AccessPatternCreate,
    ValidationResult,
    WritePatternCreate,
)
from backend.db.repositories import EntityRepository, PatternRepository

logger = logging.getLogger(__name__)

SONNET_MODEL_ID = "us.anthropic.claude-sonnet-4-20250514-v1:0"

VALIDATION_SYSTEM_PROMPT = """You are a data access pattern validator for a DynamoDB migration tool.

You will receive a user-submitted access pattern along with the project's entity list and existing patterns.
Your job is to determine whether the pattern is valid by checking:

1. **Semantic validity**: Is this a meaningful data access operation (read or write)?
   - Valid examples: "Get users by email", "Update order status", "List products by category"
   - Invalid examples: "Make coffee", "Send email notification", "Run batch job"
   - The pattern name should describe a data retrieval or data mutation operation.

2. **Context validity**: Does the pattern make sense for the project's domain?
   - Do the referenced entities exist in the project's entity list?
   - Does the combination of entities and operation make logical sense?
   - Is the pattern meaningfully different from existing patterns (not an exact duplicate)?

You MUST respond with ONLY a JSON object in this exact format:
{"valid": true, "reason": "Pattern is a valid data access operation for the project domain."}
or
{"valid": false, "reason": "Explanation of why the pattern is invalid."}

Do NOT include any text outside the JSON object. Do NOT use markdown code fences."""


class PatternValidationService:
    """Validates user-submitted access patterns using a Strands agent with Amazon Bedrock."""

    def _create_session(self) -> boto3.Session:
        """Create a boto3 session using the AWS_PROFILE env var (set by pipeline_runner)."""
        profile = os.environ.get("AWS_PROFILE", "default")
        return boto3.Session(profile_name=profile, region_name="us-east-1")

    def _create_agent(self) -> Agent:
        """Create a lightweight Strands agent for pattern validation."""
        model = BedrockModel(
            model_id=SONNET_MODEL_ID,
            boto_session=self._create_session(),
            max_tokens=1024,
        )
        return Agent(model=model, system_prompt=VALIDATION_SYSTEM_PROMPT)

    def _load_context(self, project_id: int, db: Session) -> tuple[list[str], list[str], list[str]]:
        """Load project entities and existing pattern names as context.

        Returns (entity_names, access_pattern_names, write_pattern_names).
        """
        entity_repo = EntityRepository(db)
        pattern_repo = PatternRepository(db)

        entities = entity_repo.get_by_project(project_id)
        entity_names = [e.name for e in entities]

        access_patterns = pattern_repo.get_access_patterns(project_id)
        access_pattern_names = [p.name for p in access_patterns]

        write_patterns = pattern_repo.get_write_patterns(project_id)
        write_pattern_names = [p.name for p in write_patterns]

        return entity_names, access_pattern_names, write_pattern_names

    def _check_entities_exist(
        self, referenced_entities: list[str], project_entities: list[str]
    ) -> ValidationResult | None:
        """Quick check: verify all referenced entities exist in the project.

        Returns a ValidationResult with valid=False if any are missing, or None if all exist.
        """
        project_entity_set = {e.lower() for e in project_entities}
        missing = [e for e in referenced_entities if e.lower() not in project_entity_set]
        if missing:
            return ValidationResult(
                valid=False,
                reason=f"Referenced entities not found: {', '.join(missing)}",
            )
        return None

    def _build_prompt(
        self,
        pattern_type: str,
        pattern_data: dict,
        entity_names: list[str],
        existing_pattern_names: list[str],
    ) -> str:
        """Build the validation prompt for the agent."""
        return (
            f"Validate this user-submitted {pattern_type} pattern:\n\n"
            f"Pattern data: {json.dumps(pattern_data, indent=2)}\n\n"
            f"Project entities: {', '.join(entity_names) if entity_names else '(none)'}\n\n"
            f"Existing {pattern_type} patterns: {', '.join(existing_pattern_names) if existing_pattern_names else '(none)'}\n\n"
            f"Return your validation result as JSON."
        )

    def _parse_agent_response(self, response: str) -> ValidationResult:
        """Parse the agent's JSON response into a ValidationResult."""
        # Strip markdown fences if present
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (fences)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        data = json.loads(text)
        return ValidationResult(
            valid=bool(data.get("valid", False)),
            reason=data.get("reason"),
        )

    def validate_access_pattern(
        self, project_id: int, pattern: AccessPatternCreate, db: Session
    ) -> ValidationResult:
        """Validate a user-submitted access pattern using a Strands agent."""
        entity_names, access_pattern_names, _ = self._load_context(project_id, db)

        # Quick check: verify referenced entities exist
        entity_check = self._check_entities_exist(pattern.source_entities, entity_names)
        if entity_check is not None:
            return entity_check

        # Build prompt and invoke agent
        pattern_data = {
            "name": pattern.name,
            "source_entities": pattern.source_entities,
            "requests_per_hour": pattern.requests_per_hour,
            "avg_items_returned": pattern.avg_items_returned,
            "source_code": pattern.source_code,
        }
        prompt = self._build_prompt("access", pattern_data, entity_names, access_pattern_names)

        try:
            agent = self._create_agent()
            result = agent(prompt)
            response_text = str(result)
            return self._parse_agent_response(response_text)
        except json.JSONDecodeError:
            logger.exception("Failed to parse validation agent response")
            return ValidationResult(valid=False, reason="Validation service returned an unparseable response.")
        except Exception:
            logger.exception("Validation agent error")
            return ValidationResult(valid=False, reason="Validation service encountered an error. Please try again.")

    def validate_write_pattern(
        self, project_id: int, pattern: WritePatternCreate, db: Session
    ) -> ValidationResult:
        """Validate a user-submitted write pattern using a Strands agent."""
        entity_names, _, write_pattern_names = self._load_context(project_id, db)

        # Quick check: verify referenced entities exist
        entity_check = self._check_entities_exist(pattern.target_entities, entity_names)
        if entity_check is not None:
            return entity_check

        # Build prompt and invoke agent
        pattern_data = {
            "name": pattern.name,
            "target_entities": pattern.target_entities,
            "requests_per_hour": pattern.requests_per_hour,
            "items_per_transaction": pattern.items_per_transaction,
            "source_code": pattern.source_code,
        }
        prompt = self._build_prompt("write", pattern_data, entity_names, write_pattern_names)

        try:
            agent = self._create_agent()
            result = agent(prompt)
            response_text = str(result)
            return self._parse_agent_response(response_text)
        except json.JSONDecodeError:
            logger.exception("Failed to parse validation agent response")
            return ValidationResult(valid=False, reason="Validation service returned an unparseable response.")
        except Exception:
            logger.exception("Validation agent error")
            return ValidationResult(valid=False, reason="Validation service encountered an error. Please try again.")
