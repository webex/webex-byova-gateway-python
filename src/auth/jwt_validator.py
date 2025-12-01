"""
JWT Validator for Webex Contact Center BYOVA Gateway.

This module implements JWS/JWT token validation for gRPC requests,
verifying tokens against Webex identity broker public keys.
"""

import logging
import threading
import time
from typing import Any, Dict

import jwt
import requests
from jwt import PyJWK
from jwt.exceptions import (
    DecodeError,
    ExpiredSignatureError,
    InvalidSignatureError,
)


class AccessTokenException(Exception):
    """Exception raised when token validation fails."""

    pass


class JWTValidator:
    """
    Validates JWT tokens from Webex Contact Center.

    This validator:
    - Fetches public keys from Webex JWKS endpoints
    - Validates JWT signatures using RSA public keys
    - Verifies token expiration and claims
    - Caches public keys for improved performance
    - Handles rate limiting by falling back to cache
    """

    # Valid Webex identity broker issuers for different regions
    VALID_ISSUERS = [
        "https://idbrokerbts.webex.com/idb",  # BTS US
        "https://idbrokerbts-eu.webex.com/idb",  # BTS EU
        "https://idbroker.webex.com/idb",  # Production US
        "https://idbroker-eu.webex.com/idb",  # Production EU
        "https://idbroker-b-us.webex.com/idb",  # B-US
        "https://idbroker-ca.webex.com/idb",  # Canada
    ]

    # Default identity broker URL
    DEFAULT_IDENTITY_BROKER_URL = "https://idbrokerbts.webex.com"

    # Datasource claim keys
    DATASOURCE_URL_KEY = "com.cisco.datasource.url"
    DATASOURCE_SCHEMA_KEY = "com.cisco.datasource.schema.uuid"

    # Default BYOVA schema UUID from https://github.com/webex/dataSourceSchemas
    # Path: Services/VoiceVirtualAgent/5397013b-7920-4ffc-807c-e8a3e0a18f43/schema.json
    # This should not change unless there is a major modification to the BYOVA schema
    DEFAULT_SCHEMA_UUID = "5397013b-7920-4ffc-807c-e8a3e0a18f43"

    def __init__(
        self,
        datasource_url: str,
        datasource_schema_uuid: str = None,
        cache_duration_minutes: int = 60,
    ):
        """
        Initialize JWT validator.

        Args:
            datasource_url: Expected datasource URL for claim validation
            datasource_schema_uuid: Expected schema UUID (default is standard BYOVA schema
                from https://github.com/webex/dataSourceSchemas). If None, uses DEFAULT_SCHEMA_UUID.
            cache_duration_minutes: How long to cache public keys (default 60 minutes)
        """
        self.datasource_url = datasource_url
        self.datasource_schema_uuid = datasource_schema_uuid or self.DEFAULT_SCHEMA_UUID
        self.cache_duration_seconds = cache_duration_minutes * 60

        # Cache for public keys by issuer
        self._public_keys_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_lock = threading.RLock()

        self.logger = logging.getLogger(__name__)
        self.logger.info(
            f"JWTValidator initialized with datasource URL: {datasource_url}"
        )

    def validate_token(self, token: str) -> bool:
        """
        Validate a JWT token.

        Args:
            token: The JWT token string to validate

        Returns:
            True if token is valid

        Raises:
            AccessTokenException: If token validation fails
        """
        try:
            # Decode token header to get issuer without verification
            unverified_token = jwt.decode(
                token,
                options={
                    "verify_signature": False,
                    "verify_exp": False,
                    "verify_aud": False,
                },
            )

            issuer = unverified_token.get("iss")
            if not issuer:
                raise AccessTokenException("Token missing 'iss' claim")

            # Debug logging
            self.logger.info(f"Validating token from issuer: {issuer}")
            self.logger.debug(f"Token claims (unverified): {unverified_token.keys()}")

            # Fetch public keys for this issuer
            public_keys = self._fetch_public_keys(issuer)
            num_keys = len(public_keys.get("keys", []))
            self.logger.info(f"Fetched {num_keys} public key(s) from JWKS endpoint")

            # Try to validate signature with each public key
            is_valid_signature = False
            decoded_token = None
            last_error = None

            for idx, key_data in enumerate(public_keys.get("keys", [])):
                try:
                    # Check if key_data is already a key object (from tests) or a JWK dict
                    if isinstance(key_data, dict):
                        # It's a JWK dictionary from JWKS endpoint
                        kid = key_data.get("kid", "unknown")
                        kty = key_data.get("kty", "unknown")
                        alg = key_data.get("alg", "RS256")

                        self.logger.debug(
                            f"Trying key {idx + 1}/{num_keys}: kid={kid}, kty={kty}, alg={alg}"
                        )

                        # Convert JWK to RSA public key
                        jwk = PyJWK(key_data)
                        public_key = jwk.key
                    else:
                        # It's already a key object (likely from tests)
                        self.logger.debug(
                            f"Trying key {idx + 1}/{num_keys} (direct key object)"
                        )
                        public_key = key_data
                        kid = "direct-key"

                    # Validate JWT signature and decode
                    decoded_token = jwt.decode(
                        token,
                        key=public_key,
                        algorithms=["RS256"],
                        options={
                            "verify_signature": True,
                            "verify_exp": True,
                            "verify_aud": False,  # We'll verify manually
                        },
                    )
                    is_valid_signature = True
                    self.logger.info(
                        f"JWT signature validated successfully with key kid={kid}"
                    )
                    break
                except (InvalidSignatureError, DecodeError) as e:
                    # Try next key - this is expected if key doesn't match
                    key_id = kid if "kid" in locals() else f"key-{idx}"
                    self.logger.debug(f"Key {key_id} signature validation failed: {e}")
                    last_error = e
                    continue
                except ExpiredSignatureError as e:
                    self.logger.error("JWT token is expired")
                    raise AccessTokenException("JWT token is expired") from e
                except Exception as e:
                    # Unexpected error with this key
                    key_id = kid if "kid" in locals() else f"key-{idx}"
                    self.logger.warning(
                        f"Unexpected error validating with key {key_id}: {e}"
                    )
                    last_error = e
                    continue

            if not is_valid_signature or not decoded_token:
                error_msg = f"JWT token signature not valid. Tried {num_keys} key(s)."
                if last_error:
                    error_msg += f" Last error: {last_error}"
                self.logger.error(error_msg)
                raise AccessTokenException("JWT token signature not valid")

            # Verify all claims
            if not self._verify_claims(decoded_token):
                self.logger.error("Claims validation failed")
                raise AccessTokenException("Claims validation failed")

            if not self._verify_datasource_claims(decoded_token):
                self.logger.error("Datasource claims validation failed")
                raise AccessTokenException("Datasource claims validation failed")

            self.logger.info("JWT token validated successfully")
            return True

        except AccessTokenException:
            raise
        except Exception as e:
            self.logger.error(f"Token validation failed: {e}")
            raise AccessTokenException(f"Token validation failed: {str(e)}") from e

    def _fetch_public_keys(self, issuer: str) -> Dict[str, Any]:
        """
        Fetch public keys from JWKS endpoint with caching.

        Args:
            issuer: The issuer URL from the token

        Returns:
            Dictionary containing public keys

        Raises:
            AccessTokenException: If keys cannot be fetched
        """
        with self._cache_lock:
            current_time = time.time()

            # Check cache first
            if issuer in self._public_keys_cache:
                cached_data = self._public_keys_cache[issuer]
                if current_time < cached_data.get("expiration_at", 0):
                    self.logger.debug("Returning cached public keys")
                    return cached_data.get("keys_data", {})

            # Fetch fresh keys
            try:
                # Construct JWKS URL
                if issuer:
                    jwks_url = f"{issuer}/oauth2/v2/keys/verificationjwk"
                else:
                    jwks_url = f"{self.DEFAULT_IDENTITY_BROKER_URL}/idb/oauth2/v2/keys/verificationjwk"

                self.logger.debug(f"Fetching public keys from: {jwks_url}")

                response = requests.get(jwks_url, timeout=10)

                if response.status_code == 200:
                    self.logger.info("Public keys fetched successfully")
                    keys_data = response.json()

                    # Cache the keys
                    self._public_keys_cache[issuer] = {
                        "keys_data": keys_data,
                        "expiration_at": current_time + self.cache_duration_seconds,
                    }

                    return keys_data

                elif response.status_code == 429:
                    # Rate limited - try to use cached keys even if expired
                    self.logger.warning(
                        "Rate limit exceeded, attempting to use cached keys"
                    )
                    if issuer in self._public_keys_cache:
                        self.logger.info("Using cached public keys despite rate limit")
                        return self._public_keys_cache[issuer].get("keys_data", {})
                    else:
                        raise AccessTokenException(
                            "Rate limit exceeded and no cached public keys available"
                        )

                else:
                    error_message = (
                        f"Failed to fetch public keys: HTTP {response.status_code}"
                    )
                    if response.text:
                        error_message += f" - {response.text}"
                    raise AccessTokenException(error_message)

            except requests.RequestException as e:
                self.logger.error(f"Error fetching public keys: {e}")
                # Try to use cached keys on network error
                if issuer in self._public_keys_cache:
                    self.logger.warning("Using cached keys due to network error")
                    return self._public_keys_cache[issuer].get("keys_data", {})
                raise AccessTokenException(
                    f"Error while fetching public keys: {str(e)}"
                ) from e

    def _verify_claims(self, decoded_token: Dict[str, Any]) -> bool:
        """
        Verify standard JWT claims.

        Args:
            decoded_token: The decoded JWT token

        Returns:
            True if all required claims are valid
        """
        try:
            # Verify issuer
            issuer = decoded_token.get("iss")
            if not issuer or issuer not in self.VALID_ISSUERS:
                self.logger.error(f"Invalid or missing issuer: {issuer}")
                return False

            # Verify required claims are present
            required_claims = ["aud", "sub", "jti"]
            for claim in required_claims:
                if claim not in decoded_token or not decoded_token[claim]:
                    self.logger.error(f"Missing or empty required claim: {claim}")
                    return False

            self.logger.debug("Standard claims validated successfully")
            return True

        except Exception as e:
            self.logger.error(f"Error verifying claims: {e}")
            return False

    def _verify_datasource_claims(self, decoded_token: Dict[str, Any]) -> bool:
        """
        Verify datasource-specific claims.

        Args:
            decoded_token: The decoded JWT token

        Returns:
            True if datasource claims are valid
        """
        try:
            # Verify datasource URL
            token_datasource_url = decoded_token.get(self.DATASOURCE_URL_KEY)
            if token_datasource_url != self.datasource_url:
                self.logger.error(
                    f"Datasource URL mismatch. Expected: {self.datasource_url}, "
                    f"Got: {token_datasource_url}"
                )
                return False

            # Verify datasource schema UUID
            token_schema_uuid = decoded_token.get(self.DATASOURCE_SCHEMA_KEY)
            if token_schema_uuid != self.datasource_schema_uuid:
                self.logger.error(
                    f"Datasource schema UUID mismatch. Expected: {self.datasource_schema_uuid}, "
                    f"Got: {token_schema_uuid}"
                )
                return False

            self.logger.debug("Datasource claims validated successfully")
            return True

        except Exception as e:
            self.logger.error(f"Error verifying datasource claims: {e}")
            return False
