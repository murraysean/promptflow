# ---------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# ---------------------------------------------------------
from typing import Dict

from azure.ai.ml._scope_dependent_operations import (
    OperationConfig,
    OperationsContainer,
    OperationScope,
    _ScopeDependentOperations,
)

from promptflow._sdk._errors import ConnectionClassNotFoundError
from promptflow._sdk.entities._connection import CustomConnection, _Connection
from promptflow.azure._restclient.flow_service_caller import FlowServiceCaller
from promptflow.core._connection_provider._workspace_connection_provider import WorkspaceConnectionProvider
from promptflow.core._errors import OpenURLFailedUserError


class ArmConnectionOperations(_ScopeDependentOperations):
    """ArmConnectionOperations.

    Get connections from arm api. You should not instantiate this class directly. Instead, you should
    create an PFClient instance that instantiates it for you and
    attaches it as an attribute.
    """

    def __init__(
        self,
        operation_scope: OperationScope,
        operation_config: OperationConfig,
        all_operations: OperationsContainer,
        credential,
        service_caller: FlowServiceCaller,
        **kwargs: Dict,
    ):
        super(ArmConnectionOperations, self).__init__(operation_scope, operation_config)
        self._all_operations = all_operations
        self._service_caller = service_caller
        self._credential = credential
        self._provider = WorkspaceConnectionProvider(
            self._operation_scope.subscription_id,
            self._operation_scope.resource_group_name,
            self._operation_scope.workspace_name,
            self._credential,
        )

    @classmethod
    def _convert_core_connection_to_sdk_connection(cls, core_conn):
        # TODO: Refine this and connection operation ones to (devkit) _Connection._from_core_object
        sdk_conn_mapping = _Connection.SUPPORTED_TYPES
        sdk_conn_cls = sdk_conn_mapping.get(core_conn.type)
        if sdk_conn_cls is None:
            raise ConnectionClassNotFoundError(
                f"Correspond sdk connection type not found for core connection type: {core_conn.type!r}, "
                f"please re-install the 'promptflow' package."
            )
        common_args = {
            "name": core_conn.name,
            "module": core_conn.module,
            "expiry_time": core_conn.expiry_time,
            "created_date": core_conn.created_date,
            "last_modified_date": core_conn.last_modified_date,
        }
        if sdk_conn_cls is CustomConnection:
            return sdk_conn_cls(configs=core_conn.configs, secrets=core_conn.secrets, **common_args)
        return sdk_conn_cls(**dict(core_conn), **common_args)

    def get(self, name, **kwargs):
        return self._convert_core_connection_to_sdk_connection(self._provider.get(name))

    @classmethod
    def _direct_get(cls, name, subscription_id, resource_group_name, workspace_name, credential):
        """
        This method is added for local pf_client with workspace provider to ensure we only require limited
        permission(workspace/list secrets). As create azure pf_client requires workspace read permission.
        """
        provider = WorkspaceConnectionProvider(subscription_id, resource_group_name, workspace_name, credential)
        return provider.get(name=name)

    # Keep this as promptflow tools is using this method
    _build_connection_dict = WorkspaceConnectionProvider._build_connection_dict


# Keep this for backward compatibility of promptflow-tools
OpenURLFailedUserError = OpenURLFailedUserError
