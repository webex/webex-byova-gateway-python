"""
gRPC Interceptor for JWT validation.

This module implements a gRPC server interceptor that validates JWT tokens
from request metadata before allowing requests to proceed.
"""

import logging
from typing import Callable

import grpc

from .jwt_validator import AccessTokenException, JWTValidator


class JWTAuthInterceptor(grpc.ServerInterceptor):
    """
    gRPC server interceptor that validates JWT tokens from metadata.

    This interceptor:
    - Extracts JWT token from 'authorization' metadata header
    - Validates the token using JWTValidator
    - Returns UNAUTHENTICATED status on validation failure (if enforcement enabled)
    - Supports optional enforcement for gradual rollout
    """

    def __init__(
        self,
        jwt_validator: JWTValidator,
        enabled: bool = True,
        enforce: bool = True,
    ):
        """
        Initialize JWT authentication interceptor.

        Args:
            jwt_validator: JWTValidator instance for token validation
            enabled: Whether JWT validation is enabled
            enforce: Whether to reject requests with invalid tokens
        """
        self.jwt_validator = jwt_validator
        self.enabled = enabled
        self.enforce = enforce
        self.logger = logging.getLogger(__name__)

        if not self.enabled:
            self.logger.warning(
                "JWT validation is DISABLED - all requests will be allowed"
            )
        elif not self.enforce:
            self.logger.warning(
                "JWT validation enforcement is DISABLED - invalid tokens will be logged but allowed"
            )
        else:
            self.logger.info("JWT validation is ENABLED and ENFORCED")

    def intercept_service(
        self, continuation: Callable, handler_call_details: grpc.HandlerCallDetails
    ) -> grpc.RpcMethodHandler:
        """
        Intercept gRPC service calls to validate JWT tokens.

        Args:
            continuation: Function to invoke the next interceptor or handler
            handler_call_details: Details about the RPC call

        Returns:
            RPC method handler
        """
        # If validation is disabled, proceed without checking
        if not self.enabled:
            return continuation(handler_call_details)

        # Extract token from metadata
        metadata = dict(handler_call_details.invocation_metadata)
        token = None

        # Look for authorization header (case-insensitive)
        for key in metadata:
            if key.lower() == "authorization":
                auth_value = metadata[key]
                # Handle "Bearer <token>" format
                if auth_value.startswith("Bearer "):
                    token = auth_value[7:]  # Remove "Bearer " prefix
                else:
                    token = auth_value
                break

        # Validate token
        if not token:
            error_msg = "Missing JWT token in authorization metadata"
            self.logger.warning(f"{error_msg} for method {handler_call_details.method}")

            if self.enforce:
                # Return error handler that aborts with UNAUTHENTICATED
                return self._abort_unauthenticated(error_msg)
            else:
                self.logger.info(
                    "Allowing request without token (enforcement disabled)"
                )
                return continuation(handler_call_details)

        # Validate the token
        try:
            self.jwt_validator.validate_token(token)
            self.logger.debug(
                f"JWT validated successfully for method {handler_call_details.method}"
            )

        except AccessTokenException as e:
            error_msg = f"JWT validation failed: {str(e)}"
            self.logger.error(f"{error_msg} for method {handler_call_details.method}")

            if self.enforce:
                # Return error handler that aborts with UNAUTHENTICATED
                return self._abort_unauthenticated(error_msg)
            else:
                self.logger.warning(
                    "Allowing request with invalid token (enforcement disabled)"
                )

        except Exception as e:
            error_msg = f"Unexpected error during JWT validation: {str(e)}"
            self.logger.error(f"{error_msg} for method {handler_call_details.method}")

            if self.enforce:
                # Return error handler that aborts with INTERNAL
                return self._abort_internal(error_msg)
            else:
                self.logger.warning(
                    "Allowing request due to validation error (enforcement disabled)"
                )

        # Proceed with the request
        return continuation(handler_call_details)

    def _abort_unauthenticated(self, error_message: str) -> grpc.RpcMethodHandler:
        """
        Create a handler that aborts with UNAUTHENTICATED status.

        Args:
            error_message: Error message to return

        Returns:
            RPC method handler that aborts the call
        """

        def abort(request, context):
            context.abort(grpc.StatusCode.UNAUTHENTICATED, error_message)

        return grpc.unary_unary_rpc_method_handler(
            abort,
            request_deserializer=lambda x: x,
            response_serializer=lambda x: x,
        )

    def _abort_internal(self, error_message: str) -> grpc.RpcMethodHandler:
        """
        Create a handler that aborts with INTERNAL status.

        Args:
            error_message: Error message to return

        Returns:
            RPC method handler that aborts the call
        """

        def abort(request, context):
            context.abort(grpc.StatusCode.INTERNAL, error_message)

        return grpc.unary_unary_rpc_method_handler(
            abort,
            request_deserializer=lambda x: x,
            response_serializer=lambda x: x,
        )
