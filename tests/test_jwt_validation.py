"""
Unit tests for JWT validation functionality.

This module tests the JWT validator and interceptor to ensure proper
token validation, signature verification, and claims checking.
"""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import grpc
import jwt
import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from src.auth.jwt_interceptor import JWTAuthInterceptor
from src.auth.jwt_validator import AccessTokenException, JWTValidator


class TestJWTValidator:
    """Test cases for JWTValidator class."""

    @pytest.fixture
    def rsa_keys(self):
        """Generate RSA key pair for testing."""
        private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048, backend=default_backend()
        )
        public_key = private_key.public_key()

        # Get PEM format
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        return {
            "private_key": private_key,
            "public_key": public_key,
            "private_pem": private_pem,
            "public_pem": public_pem,
        }

    @pytest.fixture
    def validator(self):
        """Create a JWTValidator instance for testing."""
        return JWTValidator(
            datasource_url="https://test-gateway.example.com:443",
            datasource_schema_uuid="5397013b-7920-4ffc-807c-e8a3e0a18f43",
            cache_duration_minutes=60,
        )

    def test_default_schema_uuid(self):
        """Test that default schema UUID is used when not provided."""
        validator = JWTValidator(datasource_url="https://test-gateway.example.com:443")
        assert (
            validator.datasource_schema_uuid == "5397013b-7920-4ffc-807c-e8a3e0a18f43"
        )
        assert validator.datasource_schema_uuid == JWTValidator.DEFAULT_SCHEMA_UUID

    @pytest.fixture
    def valid_claims(self):
        """Generate valid JWT claims."""
        return {
            "iss": "https://idbroker.webex.com/idb",
            "aud": "test-audience",
            "sub": "test-subject",
            "jti": "test-jwt-id",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "com.cisco.datasource.url": "https://test-gateway.example.com:443",
            "com.cisco.datasource.schema.uuid": "5397013b-7920-4ffc-807c-e8a3e0a18f43",
        }

    def create_test_token(self, claims, private_key):
        """Create a test JWT token."""
        return jwt.encode(claims, private_key, algorithm="RS256")

    def test_valid_token_validation(self, validator, rsa_keys, valid_claims):
        """Test successful validation of a valid token."""
        token = self.create_test_token(valid_claims, rsa_keys["private_key"])

        # Mock the public key fetching
        mock_jwks_response = {
            "keys": [
                {
                    "kty": "RSA",
                    "use": "sig",
                    "kid": "test-key-id",
                    "n": jwt.utils.base64url_encode(
                        rsa_keys["public_key"].public_numbers().n.to_bytes(256, "big")
                    ).decode("utf-8"),
                    "e": jwt.utils.base64url_encode(
                        rsa_keys["public_key"].public_numbers().e.to_bytes(3, "big")
                    ).decode("utf-8"),
                }
            ]
        }

        with patch.object(
            validator, "_fetch_public_keys", return_value=mock_jwks_response
        ):
            # Mock jwt.decode to use our public key
            with patch("jwt.decode") as mock_decode:
                mock_decode.return_value = valid_claims
                assert validator.validate_token(token) is True

    def test_expired_token_rejection(self, validator, rsa_keys, valid_claims):
        """Test rejection of an expired token."""
        expired_claims = valid_claims.copy()
        expired_claims["exp"] = datetime.now(timezone.utc) - timedelta(hours=1)

        token = self.create_test_token(expired_claims, rsa_keys["private_key"])

        # Mock the public key fetching
        mock_jwks_response = {"keys": [rsa_keys["public_key"]]}

        with patch.object(
            validator, "_fetch_public_keys", return_value=mock_jwks_response
        ):
            # The first jwt.decode call (unverified) should succeed, second should fail
            with patch("src.auth.jwt_validator.jwt.decode") as mock_decode:
                # First call returns the claims, second call raises ExpiredSignatureError
                mock_decode.side_effect = [
                    expired_claims,  # Unverified decode succeeds
                    jwt.ExpiredSignatureError("Token expired"),  # Verified decode fails
                ]
                with pytest.raises(AccessTokenException, match="JWT token is expired"):
                    validator.validate_token(token)

    def test_invalid_signature_rejection(self, validator, rsa_keys, valid_claims):
        """Test rejection of a token with invalid signature."""
        # Create token with one key
        token = self.create_test_token(valid_claims, rsa_keys["private_key"])

        # Try to validate with a different key
        other_private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048, backend=default_backend()
        )

        mock_jwks_response = {"keys": [other_private_key.public_key()]}

        with patch.object(
            validator, "_fetch_public_keys", return_value=mock_jwks_response
        ):
            # The first jwt.decode call (unverified) should succeed, second should fail
            with patch("src.auth.jwt_validator.jwt.decode") as mock_decode:
                # First call returns the claims, second call raises InvalidSignatureError
                mock_decode.side_effect = [
                    valid_claims,  # Unverified decode succeeds
                    jwt.InvalidSignatureError(
                        "Invalid signature"
                    ),  # Verified decode fails
                ]
                with pytest.raises(
                    AccessTokenException, match="JWT token signature not valid"
                ):
                    validator.validate_token(token)

    def test_missing_issuer_rejection(self, validator, rsa_keys, valid_claims):
        """Test rejection of token missing issuer claim."""
        invalid_claims = valid_claims.copy()
        del invalid_claims["iss"]

        token = self.create_test_token(invalid_claims, rsa_keys["private_key"])

        with pytest.raises(AccessTokenException, match="Token missing 'iss' claim"):
            validator.validate_token(token)

    def test_invalid_issuer_rejection(self, validator, rsa_keys, valid_claims):
        """Test rejection of token with invalid issuer."""
        invalid_claims = valid_claims.copy()
        invalid_claims["iss"] = "https://invalid-issuer.com"

        token = self.create_test_token(invalid_claims, rsa_keys["private_key"])

        mock_jwks_response = {"keys": [rsa_keys["public_key"]]}

        with patch.object(
            validator, "_fetch_public_keys", return_value=mock_jwks_response
        ):
            with patch("jwt.decode", return_value=invalid_claims):
                with pytest.raises(
                    AccessTokenException, match="Claims validation failed"
                ):
                    validator.validate_token(token)

    def test_missing_required_claims_rejection(self, validator, rsa_keys, valid_claims):
        """Test rejection of token missing required claims."""
        for claim in ["aud", "sub", "jti"]:
            invalid_claims = valid_claims.copy()
            del invalid_claims[claim]

            token = self.create_test_token(invalid_claims, rsa_keys["private_key"])

            mock_jwks_response = {"keys": [rsa_keys["public_key"]]}

            with patch.object(
                validator, "_fetch_public_keys", return_value=mock_jwks_response
            ):
                with patch("jwt.decode", return_value=invalid_claims):
                    with pytest.raises(
                        AccessTokenException, match="Claims validation failed"
                    ):
                        validator.validate_token(token)

    def test_datasource_url_mismatch_rejection(self, validator, rsa_keys, valid_claims):
        """Test rejection of token with mismatched datasource URL."""
        invalid_claims = valid_claims.copy()
        invalid_claims["com.cisco.datasource.url"] = "https://wrong-url.com:443"

        token = self.create_test_token(invalid_claims, rsa_keys["private_key"])

        mock_jwks_response = {"keys": [rsa_keys["public_key"]]}

        with patch.object(
            validator, "_fetch_public_keys", return_value=mock_jwks_response
        ):
            with patch("jwt.decode", return_value=invalid_claims):
                with pytest.raises(
                    AccessTokenException, match="Datasource claims validation failed"
                ):
                    validator.validate_token(token)

    def test_datasource_schema_uuid_mismatch_rejection(
        self, validator, rsa_keys, valid_claims
    ):
        """Test rejection of token with mismatched schema UUID."""
        invalid_claims = valid_claims.copy()
        invalid_claims["com.cisco.datasource.schema.uuid"] = "wrong-uuid"

        token = self.create_test_token(invalid_claims, rsa_keys["private_key"])

        mock_jwks_response = {"keys": [rsa_keys["public_key"]]}

        with patch.object(
            validator, "_fetch_public_keys", return_value=mock_jwks_response
        ):
            with patch("jwt.decode", return_value=invalid_claims):
                with pytest.raises(
                    AccessTokenException, match="Datasource claims validation failed"
                ):
                    validator.validate_token(token)

    def test_public_key_caching(self, validator):
        """Test that public keys are cached properly."""
        issuer = "https://idbroker.webex.com/idb"
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"keys": [{"test": "key"}]}

        with patch("requests.get", return_value=mock_response) as mock_get:
            # First call should fetch keys
            result1 = validator._fetch_public_keys(issuer)
            assert mock_get.call_count == 1

            # Second call should use cache
            result2 = validator._fetch_public_keys(issuer)
            assert mock_get.call_count == 1  # Still 1, no new call

            assert result1 == result2

    def test_rate_limit_handling(self, validator):
        """Test handling of rate limit (429) response."""
        issuer = "https://idbroker.webex.com/idb"

        # Pre-populate cache
        validator._public_keys_cache[issuer] = {
            "keys_data": {"keys": [{"test": "key"}]},
            "expiration_at": time.time() - 1,  # Expired
        }

        # Mock rate limit response
        mock_response = Mock()
        mock_response.status_code = 429

        with patch("requests.get", return_value=mock_response):
            # Should return cached keys despite being expired
            result = validator._fetch_public_keys(issuer)
            assert result == {"keys": [{"test": "key"}]}

    def test_network_error_fallback_to_cache(self, validator):
        """Test fallback to cache on network error."""
        issuer = "https://idbroker.webex.com/idb"

        # Pre-populate cache
        validator._public_keys_cache[issuer] = {
            "keys_data": {"keys": [{"test": "key"}]},
            "expiration_at": time.time() + 3600,
        }

        # Mock network error
        with patch("requests.get", side_effect=Exception("Network error")):
            result = validator._fetch_public_keys(issuer)
            assert result == {"keys": [{"test": "key"}]}


class TestJWTAuthInterceptor:
    """Test cases for JWTAuthInterceptor class."""

    @pytest.fixture
    def mock_validator(self):
        """Create a mock JWTValidator."""
        validator = Mock(spec=JWTValidator)
        validator.validate_token = Mock(return_value=True)
        return validator

    @pytest.fixture
    def interceptor(self, mock_validator):
        """Create a JWTAuthInterceptor for testing."""
        return JWTAuthInterceptor(
            jwt_validator=mock_validator,
            enabled=True,
            enforce=True,
        )

    @pytest.fixture
    def mock_handler_call_details(self):
        """Create mock handler call details."""
        details = Mock(spec=grpc.HandlerCallDetails)
        details.method = "/test.Service/TestMethod"
        return details

    def test_valid_token_allowed(self, interceptor, mock_handler_call_details):
        """Test that requests with valid tokens are allowed."""
        # Set up metadata with valid token
        mock_handler_call_details.invocation_metadata = [
            ("authorization", "Bearer valid-token-here")
        ]

        # Mock continuation
        mock_continuation = Mock(return_value="handler")

        # Intercept
        result = interceptor.intercept_service(
            mock_continuation, mock_handler_call_details
        )

        # Should call continuation
        mock_continuation.assert_called_once()
        assert result == "handler"

    def test_missing_token_rejected_when_enforced(
        self, interceptor, mock_handler_call_details
    ):
        """Test that requests without tokens are rejected when enforcement is enabled."""
        # Set up metadata without token
        mock_handler_call_details.invocation_metadata = []

        # Mock continuation
        mock_continuation = Mock(return_value="handler")

        # Intercept
        result = interceptor.intercept_service(
            mock_continuation, mock_handler_call_details
        )

        # Should NOT call continuation
        mock_continuation.assert_not_called()

        # Result should be an abort handler (not the continuation result)
        assert result != "handler"

    def test_missing_token_allowed_when_not_enforced(self, mock_validator):
        """Test that requests without tokens are allowed when enforcement is disabled."""
        interceptor = JWTAuthInterceptor(
            jwt_validator=mock_validator,
            enabled=True,
            enforce=False,
        )

        mock_handler_call_details = Mock(spec=grpc.HandlerCallDetails)
        mock_handler_call_details.method = "/test.Service/TestMethod"
        mock_handler_call_details.invocation_metadata = []

        mock_continuation = Mock(return_value="handler")

        result = interceptor.intercept_service(
            mock_continuation, mock_handler_call_details
        )

        # Should call continuation even without token
        mock_continuation.assert_called_once()
        assert result == "handler"

    def test_invalid_token_rejected_when_enforced(
        self, mock_validator, mock_handler_call_details
    ):
        """Test that requests with invalid tokens are rejected when enforcement is enabled."""
        # Set up validator to reject token
        mock_validator.validate_token.side_effect = AccessTokenException(
            "Invalid token"
        )

        interceptor = JWTAuthInterceptor(
            jwt_validator=mock_validator,
            enabled=True,
            enforce=True,
        )

        mock_handler_call_details.invocation_metadata = [
            ("authorization", "Bearer invalid-token")
        ]

        mock_continuation = Mock(return_value="handler")

        result = interceptor.intercept_service(
            mock_continuation, mock_handler_call_details
        )

        # Should NOT call continuation
        mock_continuation.assert_not_called()
        assert result != "handler"

    def test_invalid_token_allowed_when_not_enforced(self, mock_validator):
        """Test that requests with invalid tokens are allowed when enforcement is disabled."""
        mock_validator.validate_token.side_effect = AccessTokenException(
            "Invalid token"
        )

        interceptor = JWTAuthInterceptor(
            jwt_validator=mock_validator,
            enabled=True,
            enforce=False,
        )

        mock_handler_call_details = Mock(spec=grpc.HandlerCallDetails)
        mock_handler_call_details.method = "/test.Service/TestMethod"
        mock_handler_call_details.invocation_metadata = [
            ("authorization", "Bearer invalid-token")
        ]

        mock_continuation = Mock(return_value="handler")

        result = interceptor.intercept_service(
            mock_continuation, mock_handler_call_details
        )

        # Should call continuation even with invalid token
        mock_continuation.assert_called_once()
        assert result == "handler"

    def test_disabled_interceptor_allows_all(self, mock_validator):
        """Test that disabled interceptor allows all requests."""
        interceptor = JWTAuthInterceptor(
            jwt_validator=mock_validator,
            enabled=False,
            enforce=True,
        )

        mock_handler_call_details = Mock(spec=grpc.HandlerCallDetails)
        mock_handler_call_details.method = "/test.Service/TestMethod"
        mock_handler_call_details.invocation_metadata = []

        mock_continuation = Mock(return_value="handler")

        result = interceptor.intercept_service(
            mock_continuation, mock_handler_call_details
        )

        # Should call continuation without checking token
        mock_continuation.assert_called_once()
        assert result == "handler"
        mock_validator.validate_token.assert_not_called()

    def test_bearer_token_format_handling(self, interceptor, mock_handler_call_details):
        """Test proper handling of 'Bearer <token>' format."""
        mock_handler_call_details.invocation_metadata = [
            ("authorization", "Bearer test-token-123")
        ]

        mock_continuation = Mock(return_value="handler")

        interceptor.intercept_service(mock_continuation, mock_handler_call_details)

        # Should extract token without "Bearer " prefix
        interceptor.jwt_validator.validate_token.assert_called_once_with(
            "test-token-123"
        )

    def test_direct_token_format_handling(self, interceptor, mock_handler_call_details):
        """Test handling of token without 'Bearer ' prefix."""
        mock_handler_call_details.invocation_metadata = [
            ("authorization", "test-token-123")
        ]

        mock_continuation = Mock(return_value="handler")

        interceptor.intercept_service(mock_continuation, mock_handler_call_details)

        # Should use token as-is
        interceptor.jwt_validator.validate_token.assert_called_once_with(
            "test-token-123"
        )
