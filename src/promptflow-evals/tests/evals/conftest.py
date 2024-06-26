import json
import multiprocessing
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pytest_mock import MockerFixture

from promptflow.connections import AzureOpenAIConnection
from promptflow.executor._line_execution_process_pool import _process_wrapper
from promptflow.executor._process_manager import create_spawned_fork_process_manager
from promptflow.tracing._integrations._openai_injector import inject_openai_api

try:
    from promptflow.recording.local import recording_array_reset
    from promptflow.recording.record_mode import is_in_ci_pipeline, is_live, is_record, is_replay
except ImportError:
    # Run test in empty mode if promptflow-recording is not installed
    def recording_array_reset():
        pass

    def is_in_ci_pipeline():
        return False

    def is_live():
        return False

    def is_record():
        return False

    def is_replay():
        return False


PROMOTFLOW_ROOT = Path(__file__) / "../../../.."
CONNECTION_FILE = (PROMOTFLOW_ROOT / "promptflow-evals/connections.json").resolve().absolute().as_posix()
RECORDINGS_TEST_CONFIGS_ROOT = Path(PROMOTFLOW_ROOT / "promptflow-recording/recordings/local").resolve()


def pytest_configure():
    pytest.is_live = is_live()
    pytest.is_record = is_record()
    pytest.is_replay = is_replay()
    pytest.is_in_ci_pipeline = is_in_ci_pipeline()


@pytest.fixture
def model_config() -> dict:
    conn_name = "azure_open_ai_connection"

    with open(
        file=CONNECTION_FILE,
        mode="r",
    ) as f:
        dev_connections = json.load(f)

    if conn_name not in dev_connections:
        raise ValueError(f"Connection '{conn_name}' not found in dev connections.")

    model_config = AzureOpenAIConnection(**dev_connections[conn_name]["value"])

    return model_config


@pytest.fixture
def deployment_name() -> str:
    # TODO: move to config file or environment variable
    return os.environ.get("AZUREML_DEPLOYMENT_NAME", "GPT-4-Prod")


# ==================== Recording injection ====================
# To inject patches in subprocesses, add new mock method in setup_recording_injection_if_enabled
# in fork mode, this is automatically enabled.
# in spawn mode, we need to declare recording in each process separately.

SpawnProcess = multiprocessing.get_context("spawn").Process


class MockSpawnProcess(SpawnProcess):
    def __init__(self, group=None, target=None, *args, **kwargs):
        if target == _process_wrapper:
            target = _mock_process_wrapper
        if target == create_spawned_fork_process_manager:
            target = _mock_create_spawned_fork_process_manager
        super().__init__(group, target, *args, **kwargs)


@pytest.fixture
def recording_injection(mocker: MockerFixture):
    original_process_class = multiprocessing.get_context("spawn").Process
    multiprocessing.get_context("spawn").Process = MockSpawnProcess
    if "spawn" == multiprocessing.get_start_method():
        multiprocessing.Process = MockSpawnProcess

    patches = setup_recording_injection_if_enabled()

    try:
        yield
    finally:
        if pytest.is_replay or pytest.is_record:
            from promptflow.recording.local import RecordStorage

            RecordStorage.get_instance().delete_lock_file()
        if pytest.is_live:
            from promptflow.recording.local import delete_count_lock_file

            delete_count_lock_file()
        recording_array_reset()

        multiprocessing.get_context("spawn").Process = original_process_class
        if "spawn" == multiprocessing.get_start_method():
            multiprocessing.Process = original_process_class

        for patcher in patches:
            patcher.stop()


def setup_recording_injection_if_enabled():
    patches = []

    def start_patches(patch_targets):
        for target, mock_func in patch_targets.items():
            patcher = patch(target, mock_func)
            patches.append(patcher)
            patcher.start()

    if is_replay() or is_record():
        from promptflow.recording.local import RecordStorage, inject_async_with_recording, inject_sync_with_recording
        from promptflow.recording.record_mode import check_pydantic_v2

        check_pydantic_v2()
        file_path = RECORDINGS_TEST_CONFIGS_ROOT / "evals.node_cache.shelve"
        RecordStorage.get_instance(file_path)

        patch_targets = {
            "promptflow.tracing._integrations._openai_injector.inject_sync": inject_sync_with_recording,
            "promptflow.tracing._integrations._openai_injector.inject_async": inject_async_with_recording,
        }
        start_patches(patch_targets)

    if is_live() and is_in_ci_pipeline():
        from promptflow.recording.local import inject_async_with_recording, inject_sync_with_recording

        patch_targets = {
            "promptflow.tracing._integrations._openai_injector.inject_sync": inject_sync_with_recording,
            "promptflow.tracing._integrations._openai_injector.inject_async": inject_async_with_recording,
        }
        start_patches(patch_targets)

    inject_openai_api()
    return patches


def _mock_process_wrapper(*args, **kwargs):
    setup_recording_injection_if_enabled()
    return _process_wrapper(*args, **kwargs)


def _mock_create_spawned_fork_process_manager(*args, **kwargs):
    setup_recording_injection_if_enabled()
    return create_spawned_fork_process_manager(*args, **kwargs)
