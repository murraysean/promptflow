import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from promptflow._sdk._pf_client import PFClient
from promptflow._sdk.entities import AzureOpenAIConnection
from promptflow.client import load_flow
from promptflow.exceptions import UserErrorException

PROMOTFLOW_ROOT = Path(__file__) / "../../../.."

TEST_ROOT = Path(__file__).parent.parent.parent
MODEL_ROOT = TEST_ROOT / "test_configs/e2e_samples"
CONNECTION_FILE = (PROMOTFLOW_ROOT / "connections.json").resolve().absolute().as_posix()
FLOWS_DIR = (TEST_ROOT / "test_configs/flows").resolve().absolute().as_posix()
EAGER_FLOWS_DIR = (TEST_ROOT / "test_configs/eager_flows").resolve().absolute().as_posix()
FLOW_RESULT_KEYS = ["category", "evidence"]

_client = PFClient()


def clear_module_cache(module_name):
    try:
        del sys.modules[module_name]
    except Exception:
        pass


class GlobalHello:
    def __init__(self, connection: AzureOpenAIConnection):
        self.connection = connection

    def __call__(self, text: str) -> str:
        return f"Hello {text} via {self.connection.name}!"


class GlobalHelloWithInvalidInit:
    def __init__(self, connection: AzureOpenAIConnection, words: list):
        self.connection = connection

    def __call__(self, text: str) -> str:
        return f"Hello {text} via {self.connection.name}!"


def global_hello(text: str) -> str:
    return f"Hello {text}!"


def global_hello_no_hint(text) -> str:
    return f"Hello {text}!"


@pytest.mark.usefixtures(
    "use_secrets_config_file", "recording_injection", "setup_local_connection", "install_custom_tool_pkg"
)
@pytest.mark.sdk_test
@pytest.mark.e2etest
class TestFlowSave:
    @pytest.mark.parametrize(
        "save_args_overrides, expected_signature",
        [
            pytest.param(
                {
                    "entry": "hello:hello_world",
                    "python_requirements": f"{TEST_ROOT}/test_configs/functions/requirements",
                    "image": "python:3.8-slim",
                    "signature": {
                        "inputs": {
                            "text": {
                                "type": "string",
                                "description": "The text to be printed",
                            }
                        },
                        "outputs": {
                            "output": {
                                "type": "string",
                                "description": "The answer",
                            }
                        },
                    },
                    "sample": {"text": "promptflow"},
                },
                {
                    "inputs": {
                        "text": {
                            "type": "string",
                            "description": "The text to be printed",
                        }
                    },
                    "outputs": {
                        "output": {
                            "type": "string",
                            "description": "The answer",
                        }
                    },
                    "sample": "sample.json",
                },
                id="hello_world.main",
            ),
            pytest.param(
                {
                    "entry": "hello:hello_world",
                    "signature": {
                        "inputs": {
                            "text": {
                                "type": "string",
                                "description": "The text to be printed",
                            }
                        },
                    },
                },
                {
                    "inputs": {
                        "text": {
                            "type": "string",
                            "description": "The text to be printed",
                        }
                    },
                    "outputs": {
                        "output": {
                            "type": "string",
                        }
                    },
                },
                id="hello_world.partially_generate_signature",
            ),
            pytest.param(
                {
                    "entry": "hello:hello_world",
                },
                {
                    "inputs": {
                        "text": {
                            "type": "string",
                        }
                    },
                    "outputs": {
                        "output": {
                            "type": "string",
                        }
                    },
                },
                id="hello_world.generate_signature",
            ),
            pytest.param(
                {
                    "entry": "hello:hello_world",
                },
                {
                    "inputs": {
                        "text": {
                            "type": "string",
                        }
                    },
                    "outputs": {
                        "response": {
                            "type": "string",
                        },
                        "length": {
                            "type": "integer",
                        },
                    },
                },
                id="data_class_output",
            ),
            pytest.param(
                {
                    "entry": "hello:Hello",
                },
                {
                    "init": {
                        "background": {
                            "type": "string",
                            "default": "World",
                        }
                    },
                    "inputs": {
                        "text": {
                            "type": "string",
                        }
                    },
                    "outputs": {
                        "output": {
                            "type": "string",
                        },
                    },
                },
                id="class_init",
            ),
            pytest.param(
                {
                    "entry": "hello:Hello",
                },
                {
                    "init": {
                        "connection": {
                            "type": "AzureOpenAIConnection",
                        },
                        "s": {
                            "type": "string",
                        },
                        "i": {
                            "type": "integer",
                        },
                        "f": {
                            "type": "number",
                        },
                        "b": {
                            "type": "boolean",
                        },
                    },
                    "inputs": {
                        "s": {
                            "type": "string",
                        },
                        "i": {
                            "type": "integer",
                        },
                        "f": {
                            "type": "number",
                        },
                        "b": {
                            "type": "boolean",
                        },
                        "li": {
                            "type": "array",
                        },
                        "d": {
                            "type": "object",
                        },
                    },
                    "outputs": {
                        "s": {
                            "type": "string",
                        },
                        "i": {
                            "type": "integer",
                        },
                        "f": {
                            "type": "number",
                        },
                        "b": {
                            "type": "boolean",
                        },
                        "l": {
                            "type": "array",
                        },
                        "d": {
                            "type": "object",
                        },
                    },
                },
                id="class_init_complicated_ports",
            ),
        ],
    )
    def test_pf_save_succeed(self, save_args_overrides, request, expected_signature: dict):
        target_path = f"{FLOWS_DIR}/saved/{request.node.callspec.id}"
        if os.path.exists(target_path):
            shutil.rmtree(target_path)

        target_code_dir = request.node.callspec.id
        target_code_dir = re.sub(r"\.[a-z_]+$", "", target_code_dir)
        save_args = {
            # should we support save to a yaml file and do not copy code?
            "path": target_path,
            # code should be required, or we can't locate entry along with code; we can check if it's possible to infer
            # code from entry
            # all content in code will be copied
            "code": f"{TEST_ROOT}/test_configs/functions/{target_code_dir}",
        }
        save_args.update(save_args_overrides)

        pf = PFClient()
        pf.flows._save(**save_args)

        flow = load_flow(target_path)
        for key, value in expected_signature.items():
            assert flow._data[key] == value, f"key: {key}, expected value: {value}, flow._data[key]: {flow._data[key]}"

        # will we support flow as function for flex flow?
        # TODO: invoke is also not supported for flex flow for now
        # assert hello.invoke(inputs={"text": "promptflow"}) == "Hello World promptflow!"

    @pytest.mark.parametrize(
        "save_args_overrides, expected_error_type, expected_error_regex",
        [
            pytest.param(
                {
                    "entry": "hello:hello_world",
                    "signature": {
                        "inputs": {
                            "non-exist": {
                                "type": "str",
                                "description": "The text to be printed",
                            }
                        },
                    },
                },
                UserErrorException,
                r"Ports from signature: non-exist",
                id="hello_world.inputs_mismatch",
            ),
            pytest.param(
                {
                    "entry": "hello:hello_world",
                    "sample": {"non-exist": "promptflow"},
                },
                UserErrorException,
                r"Sample keys non-exist do not match the inputs text.",
                id="hello_world.sample_mismatch",
            ),
            pytest.param(
                {
                    "entry": "hello:hello_world",
                    "signature": {
                        "outputs": {
                            "non-exist": {
                                "type": "str",
                                "description": "The text to be printed",
                            }
                        },
                    },
                },
                UserErrorException,
                r"Ports from signature: non-exist",
                id="hello_world.outputs_mismatch",
            ),
            pytest.param(
                {
                    "entry": "hello:Hello",
                },
                UserErrorException,
                r"Schema validation failed: {'init.words.type'",
                id="class_init_with_list_init",
            ),
            pytest.param(
                {
                    "entry": "hello:Hello",
                },
                UserErrorException,
                r"The input 'text' is of a complex python type. Please use a dict instead",
                id="class_init_with_entity_inputs",
            ),
            pytest.param(
                {
                    "entry": "hello:Hello",
                },
                UserErrorException,
                r"The output 'output' is of a complex python type. Please use a dict instead",
                id="class_init_with_entity_outputs",
            ),
            pytest.param(
                {
                    "entry": "hello:Hello",
                },
                UserErrorException,
                r"The output 'entity' is of a complex python type. Please use a dict instead",
                id="class_init_with_dataclass_entity_fields",
            ),
        ],
    )
    def test_pf_save_failed(self, save_args_overrides, request, expected_error_type, expected_error_regex: str):
        target_path = f"{FLOWS_DIR}/saved/{request.node.callspec.id}"
        if os.path.exists(target_path):
            shutil.rmtree(target_path)
        target_code_dir = request.node.callspec.id
        target_code_dir = re.sub(r"\.[a-z_]+$", "", target_code_dir)
        save_args = {
            # should we support save to a yaml file and do not copy code?
            "path": target_path,
            # code should be required, or we can't locate entry along with code; we can check if it's possible to infer
            # code from entry
            # all content in code will be copied
            "code": f"{TEST_ROOT}/test_configs/functions/{target_code_dir}",
        }
        save_args.update(save_args_overrides)

        pf = PFClient()
        with pytest.raises(expected_error_type, match=expected_error_regex):
            pf.flows._save(**save_args)

    def test_pf_save_callable_class(self):
        pf = PFClient()
        target_path = f"{FLOWS_DIR}/saved/hello_callable"
        if os.path.exists(target_path):
            shutil.rmtree(target_path)
        pf.flows._save(
            entry=GlobalHello,
            path=target_path,
        )

        flow = load_flow(target_path)
        assert flow._data == {
            "entry": "test_flow_save:GlobalHello",
            "init": {
                "connection": {
                    "type": "AzureOpenAIConnection",
                }
            },
            "inputs": {
                "text": {
                    "type": "string",
                }
            },
            "outputs": {
                "output": {
                    "type": "string",
                },
            },
        }

    def test_pf_save_callable_function(self):
        pf = PFClient()
        target_path = f"{FLOWS_DIR}/saved/hello_callable"
        if os.path.exists(target_path):
            shutil.rmtree(target_path)
        pf.flows._save(
            entry=global_hello,
            path=target_path,
        )

        flow = load_flow(target_path)
        assert flow._data == {
            "entry": "test_flow_save:global_hello",
            "inputs": {
                "text": {
                    "type": "string",
                }
            },
            "outputs": {
                "output": {
                    "type": "string",
                },
            },
        }

    def test_infer_signature(self):
        pf = PFClient()
        flow_meta = pf.flows.infer_signature(entry=global_hello)
        assert flow_meta == {
            "inputs": {
                "text": {
                    "type": "string",
                }
            },
            "outputs": {
                "output": {
                    "type": "string",
                },
            },
        }

        with pytest.raises(UserErrorException, match="Schema validation failed: {'init.words.type'"):
            pf.flows.infer_signature(entry=GlobalHelloWithInvalidInit)

        flow_meta = pf.flows.infer_signature(entry=global_hello_no_hint)
        assert flow_meta == {
            "inputs": {
                "text": {
                    # port without type hint will be treated as a dict
                    "type": "object",
                }
            },
            "outputs": {
                "output": {
                    "type": "string",
                },
            },
        }

    def test_public_infer_signature(self):
        pf = PFClient()
        assert pf.flows.infer_signature(entry=global_hello) == {
            "inputs": {
                "text": {
                    "type": "string",
                }
            },
            "outputs": {
                "output": {
                    "type": "string",
                },
            },
        }

    def test_public_save(self):
        pf = PFClient()
        with tempfile.TemporaryDirectory() as tempdir:
            pf.flows.save(entry=global_hello, path=tempdir)
            assert load_flow(tempdir)._data == {
                "entry": "test_flow_save:global_hello",
                "inputs": {
                    "text": {
                        "type": "string",
                    }
                },
                "outputs": {
                    "output": {
                        "type": "string",
                    },
                },
            }

    def test_public_save_with_path_sample(self):
        pf = PFClient()
        with tempfile.TemporaryDirectory() as tempdir:
            with open(f"{tempdir}/sample.json", "w") as f:
                json.dump(
                    {
                        "text": "promptflow",
                    },
                    f,
                )
            pf.flows.save(entry=global_hello, path=f"{tempdir}/flow", sample=f"{tempdir}/sample.json")
            assert load_flow(f"{tempdir}/flow")._data == {
                "entry": "test_flow_save:global_hello",
                "inputs": {
                    "text": {
                        "type": "string",
                    }
                },
                "outputs": {
                    "output": {
                        "type": "string",
                    },
                },
                "sample": "sample.json",
            }

    def test_flow_save_file_code(self):
        pf = PFClient()
        with tempfile.TemporaryDirectory() as temp_dir:
            pf.flows.save(
                entry="hello_world",
                code=f"{TEST_ROOT}/test_configs/functions/file_code/hello.py",
                path=temp_dir,
            )
            flow = load_flow(temp_dir)
            assert flow._data == {
                "entry": "hello:hello_world",
                "inputs": {
                    "text": {
                        "type": "string",
                    }
                },
                "outputs": {
                    "output": {
                        "type": "string",
                    }
                },
            }
            assert os.listdir(temp_dir) == ["flow.flex.yaml", "hello.py"]
