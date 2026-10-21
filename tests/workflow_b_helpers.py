"""Run Workflow B's own SQL and Code-node JavaScript, read from the exported workflow JSON.

A change made in the n8n editor and exported is what the tests check. n8n passes positional
parameters ($1, $2, ...); `node_query` rewrites them to named pg8000 parameters.
`run_code_node` executes a Code node under Node.js with a stub `$input` (one or more items), as
n8n's "run once for all items" mode does, and a stub `$('Node name')` that returns the outputs given
for earlier nodes. `.item` is the first item, so "run once for each item" nodes run on one item.
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

STAGE1_NODE = "Stage 1 · SQL pre-filter"
STAGE1_RECORD_NODE = "Record · Stage 1 funnel"
STAGE1_ANALYZE_NODE = "Stage 1 · Refresh planner statistics"
STAGE2_LOAD_NODE = "Stage 2 · Load product rules"
STAGE2_CARDS_NODE = "Stage 2 · Build rule cards"
STAGE2_CLASSIFY_NODE = "Stage 2 · Classify pairs"
STAGE2_RECORD_NODE = "Record · Stage 2 funnel"
RUN_PARAMS = {"$1": ":run_id", "$2": ":batch_id"}
TIMED_PARAMS = {"$1": ":run_id", "$2": ":batch_id", "$3": ":started_at"}
CLASSIFY_PARAMS = {"$1": ":run_id", "$2": ":batch_id", "$3": ":cards", "$4": ":started_at"}

CODE_NODE_HARNESS = """
const { items, nodes } = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const wrap = (list) => ({
  first: () => ({ json: list[0] }),
  all: () => list.map((json) => ({ json })),
  item: { json: list[0] },
});
const $input = wrap(items);
const $ = (name) => {
  if (!(name in nodes)) {
    throw new Error(`no stub output for node ${name}`);
  }
  return wrap(nodes[name]);
};
const run = new Function('$input', '$', process.argv[1]);
process.stdout.write(JSON.stringify(run($input, $)));
"""


def workflow_node(name: str, workflow_file: Path = WORKFLOW) -> dict[str, Any]:
    workflow = json.loads(workflow_file.read_text(encoding="utf-8"))[0]
    node: dict[str, Any] = next(n for n in workflow["nodes"] if n["name"] == name)
    return node


def node_query(name: str, placeholders: dict[str, str], workflow_file: Path = WORKFLOW) -> str:
    query: str = workflow_node(name, workflow_file)["parameters"]["query"]
    return re.sub(r"\$\d+", lambda m: placeholders[m.group(0)], query)


def run_code_node(
    name: str,
    item: dict[str, Any] | list[dict[str, Any]],
    nodes: dict[str, list[dict[str, Any]]] | None = None,
    workflow_file: Path = WORKFLOW,
) -> list[dict[str, Any]]:
    assert NODE_BINARY is not None
    items = item if isinstance(item, list) else [item]
    js_code = workflow_node(name, workflow_file)["parameters"]["jsCode"]
    completed = subprocess.run(
        [NODE_BINARY, "-e", CODE_NODE_HARNESS, js_code],
        input=json.dumps({"items": items, "nodes": nodes or {}}, default=str),
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


def run_stage1(conn: Any, run_id: int, batch_id: uuid.UUID) -> None:
    params = {"run_id": str(run_id), "batch_id": batch_id}
    started = single_row(conn, conn.run(node_query(STAGE1_NODE, RUN_PARAMS), **params))
    conn.run(
        node_query(STAGE1_RECORD_NODE, TIMED_PARAMS),
        **params,
        started_at=started["stage1_started_at"],
    )
    conn.run(node_query(STAGE1_ANALYZE_NODE, {}))


def build_cards(conn: Any, run_id: int, batch_id: uuid.UUID) -> dict[str, Any]:
    params = {"run_id": str(run_id), "batch_id": batch_id}
    loaded = single_row(conn, conn.run(node_query(STAGE2_LOAD_NODE, RUN_PARAMS), **params))
    output = run_code_node(STAGE2_CARDS_NODE, loaded)
    assert len(output) == 1
    item: dict[str, Any] = output[0]["json"]
    return item


def classify_and_record(conn: Any, item: dict[str, Any], cards: list[Any]) -> dict[str, Any]:
    params = {"run_id": item["run_id"], "batch_id": uuid.UUID(item["batch_id"])}
    classified = single_row(
        conn,
        conn.run(
            node_query(STAGE2_CLASSIFY_NODE, CLASSIFY_PARAMS),
            **params,
            cards=json.dumps(cards),
            started_at=item["stage2_started_at"],
        ),
    )
    recorded = single_row(
        conn,
        conn.run(
            node_query(STAGE2_RECORD_NODE, TIMED_PARAMS),
            **params,
            started_at=classified["stage2_started_at"],
        ),
    )
    return {**classified, **recorded}


def run_stage2(conn: Any, run_id: int, batch_id: uuid.UUID) -> dict[str, Any]:
    """Chain the four Stage 2 nodes exactly as n8n does, each fed with the previous output."""
    item = build_cards(conn, run_id, batch_id)
    return {**classify_and_record(conn, item, item["cards"]), "cards": item["cards"]}
