"""The loader's give-up point must equal the queue's redrive limit, and the DLQs must be alarmed."""

from __future__ import annotations

import re
from pathlib import Path

from lambdas.load_chunk.handler import MAX_RECEIVES

SERVERLESS = (Path(__file__).resolve().parents[2] / "serverless.yml").read_text()


def test_loader_gives_up_on_the_receive_the_queue_redrives_on() -> None:
    match = re.search(r"maxReceiveCount:\s*(\d+)", SERVERLESS)
    assert match is not None
    assert int(match.group(1)) == MAX_RECEIVES


def test_both_dead_letter_queues_have_a_visible_message_alarm() -> None:
    alarms = re.findall(r"MetricName: ApproximateNumberOfMessagesVisible", SERVERLESS)
    assert len(alarms) == 2
    assert "QueueName\n            Value: !GetAtt IngestDlq.QueueName" in SERVERLESS
    assert "QueueName\n            Value: !GetAtt SplitFailuresQueue.QueueName" in SERVERLESS
