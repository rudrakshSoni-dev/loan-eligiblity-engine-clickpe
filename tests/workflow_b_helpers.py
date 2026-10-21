"""Run Workflow B's own SQL and Code-node JavaScript, read from the exported workflow JSON.

A change made in the n8n editor and exported is what the tests check. n8n passes positional
parameters ($1, $2, ...); `node_query` rewrites them to named pg8000 parameters.
`run_code_node` executes a Code node under Node.js with a stub `$input`, as n8n's
"run once for all items" mode does.
"""

import json
import re
import shutil
import subprocess
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

WORKFLOW = Path(__file__).resolve().parents[1] / "n8n" / "workflows" / "workflow-b-matching.json"
NODE_BINARY = shutil.which("node")

CODE_NODE_HARNESS = """
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const $input = { first: () => ({ json: input }), all: () => [{ json: input }] };
const run = new Function('$input', process.argv[1]);
process.stdout.write(JSON.stringify(run($input)));
"""


def workflow_node(name: str) -> dict[str, Any]:
    workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))[0]
    node: dict[str, Any] = next(n for n in workflow["nodes"] if n["name"] == name)
    return node


def node_query(name: str, placeholders: dict[str, str]) -> str:
    query: str = workflow_node(name)["parameters"]["query"]
    return re.sub(r"\$\d+", lambda m: placeholders[m.group(0)], query)


def run_code_node(name: str, item: dict[str, Any]) -> list[dict[str, Any]]:
    assert NODE_BINARY is not None
    completed = subprocess.run(
        [NODE_BINARY, "-e", CODE_NODE_HARNESS, workflow_node(name)["parameters"]["jsCode"]],
        input=json.dumps(item, default=str),
        capture_output=True,
        text=True,
        check=True,
    )
    output: list[dict[str, Any]] = json.loads(completed.stdout)
    return output


def new_batch(conn: Any, status: str = "matching") -> uuid.UUID:
    batch_id = uuid.uuid4()
    conn.run(
        "INSERT INTO upload_batches (id, s3_key, status) VALUES (:id, :key, :status)",
        id=batch_id,
        key=f"uploads/{batch_id}.csv",
        status=status,
    )
    return batch_id


def new_run(conn: Any, batch_id: uuid.UUID) -> int:
    rows = conn.run(
        "INSERT INTO pipeline_runs (batch_id, total_pairs) VALUES (:id, 0) RETURNING id",
        id=batch_id,
    )
    return int(rows[0][0])


def add_user(
    conn: Any,
    batch_id: uuid.UUID,
    income: int,
    score: int,
    age: int = 30,
    employment: str = "Salaried",
) -> uuid.UUID:
    user_id = uuid.uuid4()
    conn.run(
        "INSERT INTO users (user_id, name, email, monthly_income, credit_score,"
        " employment_status, age, batch_id) VALUES (:id, 'T', 't@example.invalid', :income,"
        " :score, :employment, :age, :batch)",
        id=user_id,
        income=Decimal(income),
        score=score,
        employment=employment,
        age=age,
        batch=batch_id,
    )
    return user_id


def add_product(conn: Any, name: str, active: bool = True, **criteria: Any) -> int:
    columns = ["source", "product_name", "active", *criteria]
    values = [":source", ":name", ":active", *(f":{c}" for c in criteria)]
    rows = conn.run(
        f"INSERT INTO loan_products ({', '.join(columns)}) VALUES ({', '.join(values)})"
        " RETURNING id",
        source="test",
        name=name,
        active=active,
        **criteria,
    )
    return int(rows[0][0])


def single_row(conn: Any, rows: list[list[Any]]) -> dict[str, Any]:
    assert len(rows) == 1
    return dict(zip([c["name"] for c in conn.columns], rows[0], strict=True))
