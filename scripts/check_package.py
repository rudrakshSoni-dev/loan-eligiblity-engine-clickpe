"""Import every runtime module from the packaged Lambda zip in a clean interpreter.

`sls package`, `validate-template` and `cfn-lint` cannot see a dependency that
fails at import time (T10 found `scramp` crashing without its dist-info), so
this check runs the imports the Lambdas will run, with only the zip on the path.
"""

import json
import logging
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

RUNTIME_MODULES = (
    "pg8000.native",
    "lambdas.get_upload_url.handler",
    "lambdas.split_csv.handler",
    "lambdas.load_chunk.handler",
    "lambdas.batch_status.handler",
    "lambdas.shared.config",
    "lambdas.shared.db",
    "lambdas.shared.batches",
    "lambdas.shared.logging",
    "lambdas.shared.uploads",
    "lambdas.shared.validation",
    "lambdas.shared.chunks",
    "lambdas.shared.loading",
    "lambdas.shared.status",
    "lambdas.shared.splitting",
    "lambdas.shared.notify",
)

REQUIRED_FILES = ("lambdas/shared/rds-global-bundle.pem",)

logger = logging.getLogger("check_package")


def import_failures(package_dir: Path, modules: tuple[str, ...]) -> dict[str, str]:
    """Return module → error for each module that fails to import from package_dir alone."""
    failures: dict[str, str] = {}
    for module in modules:
        probe = f"import sys; sys.path[:0] = [{str(package_dir)!r}]; import {module}"
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-c", probe],
            capture_output=True,
            text=True,
            cwd=package_dir,
            check=False,
        )
        if result.returncode != 0:
            failures[module] = result.stderr.strip().splitlines()[-1]
    return failures


def main(zip_path: str) -> int:
    """Extract the zip to a temporary directory and report import failures."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(tmp)
        failures = import_failures(Path(tmp), RUNTIME_MODULES)
        failures.update(
            {
                name: "missing from package"
                for name in REQUIRED_FILES
                if not (Path(tmp) / name).is_file()
            }
        )
    stage = "package_imports_failed" if failures else "package_imports_ok"
    logger.info(json.dumps({"stage": stage, "count": len(RUNTIME_MODULES), "failures": failures}))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
