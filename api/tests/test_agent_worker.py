import pytest

from app.agent_store.worker import parse_args


def test_worker_cli_accepts_only_bounded_batch_and_poll_values() -> None:
    args = parse_args(["--batch-size", "25", "--poll-seconds", "1.5"])
    assert args.batch_size == 25
    assert args.poll_seconds == 1.5
    with pytest.raises(SystemExit):
        parse_args(["--batch-size", "9999"])
    with pytest.raises(SystemExit):
        parse_args(["--poll-seconds", "600"])
