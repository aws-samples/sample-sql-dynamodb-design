# Security

## Non-Production Disclaimer

This tool and its sample .NET project are provided as a reference implementation for educational and developer-tooling purposes. They are **not intended for direct use in production environments** without additional security hardening, testing, and review appropriate to your organization's requirements.

## Reporting Vulnerabilities

If you discover a potential security issue in this project, please report it to AWS Security via email at [aws-security@amazon.com](mailto:aws-security@amazon.com). Please do **not** create a public issue.

## AWS Services Used

This project interacts with the following AWS services:

- **Amazon Bedrock** — The pipeline invokes `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` for Claude Sonnet 4 and Claude Opus 4.6. Source code excerpts and extracted access patterns are sent in prompts to the foundation models.
- **AWS DynamoDB MCP Server** — Launched as an optional local subprocess via `uvx awslabs.dynamodb-mcp-server@latest` to retrieve DynamoDB modeling guidance over stdio. Falls back to bundled local templates if unavailable. No DynamoDB tables are created or queried at runtime.

## Known Security Considerations

The following items are acknowledged as accepted technical debt in this reference implementation:

- **`except Exception: pass` in 4 cleanup locations (Low)** — Non-critical cleanup paths in `backend/services/pipeline_runner.py` (log handler close and UI log callback), `backend/services/consensus.py` (UI log emit), and `backend/api/routes/pipeline.py` (consensus report read) silently swallow all exceptions.
- **`host="0.0.0.0"` in dev server entry point (Medium)** — `backend/run.py` binds Uvicorn to all network interfaces. Standard development pattern; the README already shows the safer `127.0.0.1` alternative for routine local work.

## Resource Cleanup

When you are done evaluating this tool:

1. **Stop running services** — Stop the Vite dev server and the FastAPI backend (`Ctrl+C` in each terminal).
2. **Delete the local SQLite database** — Remove `app.db` at the repo root to clear all project, scope, pattern, override, and pipeline-run history.
3. **Delete pipeline output** — Remove the `output/` directory (`access_patterns.md`, `entity_metrics.json`, `dynamo_model.md`, `dynamo_model.json`, `validation_report.md`, `capacity_analysis.md`, and scoped variants).
4. **Delete per-run logs** — Remove the `logs/` directory.
5. **Delete cached MCP guidance** — Remove `templates/mcp_dynamodb_guidance.md` and `templates/dynamodb_knowledge_base.md`. Both are regenerated on the next pipeline run.
6. **Delete Roslyn analyzer build output** (optional) — Remove `tools/analyzer/bin/` and `tools/analyzer/obj/`.
7. **Revoke any IAM credentials** — Sign out of any SSO sessions (`aws sso logout --profile <your-profile>`) and revoke any access keys created specifically for evaluating this tool.

## Production Hardening Recommendations

Before adapting this tool for use in a shared, hosted, or production-adjacent environment, consider the following:

### IAM Permissions

Apply the principle of least privilege. The minimum IAM permissions required are:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:<Region>::foundation-model/anthropic.claude-sonnet-4-20250514-v1:0",
        "arn:aws:bedrock:<Region>::foundation-model/anthropic.claude-opus-4-6-v1",
        "arn:aws:bedrock:*:<Account>:inference-profile/us.anthropic.claude-sonnet-4-20250514-v1:0",
        "arn:aws:bedrock:*:<Account>:inference-profile/us.anthropic.claude-opus-4-6-v1"
      ]
    }
  ]
}
```

### Logging and Monitoring

- Set the backend log level to `WARNING` or higher in shared environments.
- Rotate and protect per-run log files under `logs/`.
- Enable **AWS CloudTrail** for Bedrock API call auditing.
- Enable Bedrock model invocation logging if you require a record of prompts and completions, and review the resulting CloudWatch log group access controls.

### Credential Management

- Do not hardcode AWS credentials in the local SQLite database, project files, or `.env` files committed to source control.
- Use IAM roles (EC2 instance profile, ECS task role, Lambda execution role) for non-local deployments.
- For local development, use short-lived credentials via AWS SSO or assumed roles.

## Dependencies

This project depends on the following packages. Review and pin versions appropriate to your organization's policies.

### Backend (Python)

| Package | Constraint | Purpose |
|---------|-----------|---------|
| fastapi | >=0.115.0 | HTTP API framework |
| uvicorn[standard] | >=0.30.0 | ASGI server |
| sqlalchemy | >=2.0.0 | ORM and persistence |
| pydantic | >=2.0.0 | Request/response validation |
| sse-starlette | >=2.0.0 | Server-sent events for pipeline progress |
| strands-agents | latest | Agent orchestration framework |
| strands-agents-tools | latest | Tool definitions for agents |
| boto3 (transitive) | latest | AWS SDK for Bedrock |

### Frontend (Node)

| Package | Constraint | Purpose |
|---------|-----------|---------|
| react | ^18.3.1 | UI framework |
| react-dom | ^18.3.1 | DOM renderer |
| react-router-dom | ^6.28.0 | Client-side routing |
| axios | ^1.16.1 | HTTP client |
| follow-redirects | ^1.16.0 | Pinned via `overrides` for advisory remediation |
| vite | ^6.0.0 | Dev server and bundler (dev) |
| typescript | ~5.6.2 | Type checker (dev) |
