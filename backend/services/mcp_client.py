"""
MCP Client for AWS DynamoDB MCP Server.

Provides programmatic access to the DynamoDB MCP server tools:
- dynamodb_data_modeling: Expert design guidance prompt
- dynamodb_data_model_validation: Validates model against DynamoDB Local
- compute_performances_and_costs: Calculates RCU/WCU and costs
"""

import subprocess
import json
import os
import sys
import threading
import logging

logger = logging.getLogger(__name__)


class DynamoDBMCPClient:
    """Client that communicates with the DynamoDB MCP server via stdio."""

    def __init__(self, aws_profile: str = None, aws_region: str = "us-east-1"):
        self.aws_profile = aws_profile or os.environ.get("AWS_PROFILE", "default")
        self.aws_region = aws_region
        self._process = None
        self._request_id = 0
        self._lock = threading.Lock()

    def _get_command(self):
        """Get the command to start the MCP server."""
        if sys.platform == "win32":
            return [
                "uv", "tool", "run",
                "--from", "awslabs.dynamodb-mcp-server@latest",
                "awslabs.dynamodb-mcp-server.exe"
            ]
        else:
            return ["uvx", "awslabs.dynamodb-mcp-server@latest"]

    def _start_server(self):
        """Start the MCP server process."""
        if self._process and self._process.poll() is None:
            logger.debug("MCP server already running (pid=%s)", self._process.pid)
            return

        env = os.environ.copy()
        env["FASTMCP_LOG_LEVEL"] = "ERROR"
        env["AWS_PROFILE"] = self.aws_profile
        env["AWS_REGION"] = self.aws_region

        cmd = self._get_command()
        logger.info(f"Starting DynamoDB MCP server: {' '.join(cmd)}")

        self._process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            encoding="utf-8",
            errors="replace"
        )

        # Send initialize request
        self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "sql-to-dynamodb-design-mentor", "version": "1.0.0"}
        })

        # Send initialized notification
        self._send_notification("notifications/initialized", {})

    def _send_request(self, method: str, params: dict) -> dict:
        """Send a JSON-RPC request and return the response."""
        with self._lock:
            self._request_id += 1
            request = {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
                "params": params
            }

            request_str = json.dumps(request) + "\n"
            self._process.stdin.write(request_str)
            self._process.stdin.flush()

            # Read response line
            response_line = self._process.stdout.readline()
            if not response_line:
                raise RuntimeError("MCP server closed connection")

            response = json.loads(response_line.strip())
            if "error" in response:
                raise RuntimeError(f"MCP error: {response['error']}")

            return response.get("result", {})

    def _send_notification(self, method: str, params: dict):
        """Send a JSON-RPC notification (no response expected)."""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        notification_str = json.dumps(notification) + "\n"
        self._process.stdin.write(notification_str)
        self._process.stdin.flush()

    def call_tool(self, tool_name: str, arguments: dict = None) -> str:
        """Call an MCP tool and return the text result."""
        logger.debug("MCP call_tool: %s, args=%s", tool_name, arguments)
        self._start_server()

        result = self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments or {}
        })

        # Extract text content from result
        content = result.get("content", [])
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item["text"])
            elif isinstance(item, str):
                texts.append(item)

        return "\n".join(texts) if texts else str(result)

    def get_modeling_guidance(self) -> str:
        """Get the DynamoDB data modeling expert prompt."""
        logger.debug("Requesting DynamoDB modeling guidance from MCP server")
        return self.call_tool("dynamodb_data_modeling")

    def validate_model(self) -> str:
        """Validate the DynamoDB data model against DynamoDB Local."""
        return self.call_tool("dynamodb_data_model_validation")

    def compute_costs(self) -> str:
        """Calculate RCU/WCU and costs from access patterns."""
        return self.call_tool("compute_performances_and_costs")

    def close(self):
        """Shut down the MCP server process."""
        if self._process and self._process.poll() is None:
            try:
                self._process.stdin.close()
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                self._process.kill()
            self._process = None

    def __del__(self):
        self.close()


def get_mcp_modeling_guidance(aws_profile: str = None, aws_region: str = "us-east-1") -> str:
    """Convenience function to fetch DynamoDB modeling guidance from the MCP server.
    Returns the expert prompt text, or falls back to local template if MCP fails."""
    try:
        client = DynamoDBMCPClient(aws_profile=aws_profile, aws_region=aws_region)
        guidance = client.get_modeling_guidance()
        client.close()
        if guidance and len(guidance) > 100:
            logger.info(f"Loaded DynamoDB modeling guidance from MCP server ({len(guidance)} chars)")
            return guidance
    except Exception as e:
        logger.warning(f"MCP server unavailable, falling back to local templates: {e}")

    # Fallback to local template
    local_path = os.path.join(os.path.dirname(__file__), "..", "..", "templates", "dynamodb_best_practices.md")
    if os.path.exists(local_path):
        with open(local_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    return ""
