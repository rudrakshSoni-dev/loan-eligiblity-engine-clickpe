"""Guards the package layout: every Lambda package must import from the repo root."""

import importlib

import pytest

LAMBDA_PACKAGES = [
    "lambdas.shared",
    "lambdas.get_upload_url",
    "lambdas.split_csv",
    "lambdas.load_chunk",
    "lambdas.batch_status",
]


@pytest.mark.parametrize("name", LAMBDA_PACKAGES)
def test_lambda_package_imports_and_is_documented(name: str) -> None:
    module = importlib.import_module(name)
    assert module.__doc__, f"{name} needs a package docstring"
