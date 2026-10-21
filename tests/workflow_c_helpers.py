"""Where Workflow C lives, shared by the wiring tests of B (hand-off) and C."""

from pathlib import Path

WORKFLOW_C = (
    Path(__file__).resolve().parents[1] / "n8n" / "workflows" / "workflow-c-notification.json"
)
WORKFLOW_C_ID = "wfcnotification01"
