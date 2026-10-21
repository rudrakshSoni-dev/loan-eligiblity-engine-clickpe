"""Workflow E's node names and file path, shared by its wiring, Code-node and database tests."""

from pathlib import Path

WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / "n8n" / "workflows"
WORKFLOW_E = WORKFLOWS_DIR / "workflow-e-error-handler.json"
WORKFLOW_E_ID = "wferrorhandler01"

TRIGGER_NODE = "Trigger · Workflow failed (Error Workflow)"
FORMAT_NODE = "Format · Build alert"
INSERT_NODE = "Record · Insert error"
LOAD_NODE = "Alert · Load recipient"
CHECK_NODE = "Alert · Check recipient"
SES_NODE = "Alert · SES email"
SENT_NODE = "Record · Alert sent"
FAILED_NODE = "Record · Alert failed"

INSERT_PARAMS = {
    "$1": ":workflow_id",
    "$2": ":workflow_name",
    "$3": ":execution_id",
    "$4": ":execution_url",
    "$5": ":node_name",
    "$6": ":mode",
    "$7": ":error_message",
    "$8": ":error_stack",
}
OUTCOME_PARAMS = {"$1": ":record_id", "$2": ":detail"}
