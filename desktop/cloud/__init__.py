"""SplatfastK1 cloud integration — currently just Replicate."""
from desktop.cloud.replicate_client import (
    DEFAULT_MODEL,
    ReplicateError,
    cancel_prediction,
    download_output,
    get_latest_version_id,
    poll_prediction,
    submit_prediction,
    test_connection,
    upload_file,
)

__all__ = [
    "DEFAULT_MODEL",
    "ReplicateError",
    "cancel_prediction",
    "download_output",
    "get_latest_version_id",
    "poll_prediction",
    "submit_prediction",
    "test_connection",
    "upload_file",
]
