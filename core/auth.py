#!/usr/bin/env python3
"""
Authentication with rotating tokens.
Tokens change every N seconds, so leaked tokens expire automatically.
"""
import os
import time
import hmac
import hashlib
import secrets
import threading


class Auth:
    """
    Rotating token authentication.
    
    Tokens are generated from a master secret + time window.
    When the window rolls over, all old tokens become invalid.
    """
    
    def __init__(
        self,
        master_secret=None,
        rotation_seconds=3600,
        grace_windows=1,
    ):
        """
        Args:
            master_secret: Server master secret (stays on server)
            rotation_seconds: How often tokens rotate (default 1 hour)
            grace_windows: How many previous windows are still accepted
                           (1 = accept current + 1 previous = up to 2h)
        """
        self.master_secret = (
            master_secret
            or os.environ.get('RSC_AUTH_SECRET')
            or 'SHELL_ACCESS_2024'
        )
        self.rotation_seconds = rotation_seconds
        self.grace_windows = grace_windows
        
        self._lock = threading.Lock()
        self._last_window = -1
        self._current_token = None
        
        # Generate initial token
        self._rotate_if_needed(force=True)
    
    # ============================================
    # Core: time-window token generation
    # ============================================
    def _window_number(self, timestamp=None):
        """Get current time window number"""
        ts = timestamp if timestamp is not None else time.time()
        return int(ts // self.rotation_seconds)
    
    def _generate_for_window(self, window_num):
        """
        Generate a token for a given time window.
        Uses HMAC so tokens can't be reversed without master secret.
        """
        msg = f"rsc-token-{window_num}".encode()
        digest = hmac.new(
            self.master_secret.encode(),
            msg,
            hashlib.sha256,
        ).hexdigest()
        # Take first 32 chars for token
        return digest[:32].upper()
    
    def _rotate_if_needed(self, force=False):
        """Rotate token if window changed"""
        with self._lock:
            current_window = self._window_number()
            if force or current_window != self._last_window:
                self._last_window = current_window
                self._current_token = self._generate_for_window(current_window)
                return True
            return False
    
    # ============================================
    # Public API
    # ============================================
    @property
    def token(self):
        """Get current valid token"""
        self._rotate_if_needed()
        return self._current_token
    
    @property
    def time_until_rotation(self):
        """Seconds until next rotation"""
        now = time.time()
        next_rotation = (self._window_number() + 1) * self.rotation_seconds
        return max(0, int(next_rotation - now))
    
    def validate(self, provided_token):
        """
        Validate a token against current + grace windows.
        Returns True if valid.
        """
        if not provided_token:
            return False
        
        self._rotate_if_needed()
        current_window = self._window_number()
        
        # Check current and grace windows
        for offset in range(self.grace_windows + 1):
            window = current_window - offset
            expected = self._generate_for_window(window)
            
            if hmac.compare_digest(
                expected.encode(),
                provided_token.encode(),
            ):
                return True
        
        return False
    
    def validate_message(self, message):
        """
        Validate "AUTH:<token>" message.
        Returns (is_valid, token_used).
        """
        if not message or not message.startswith('AUTH:'):
            return False, None
        
        token = message.split(':', 1)[1].strip()
        return self.validate(token), token
    
    def parse_auth(self, message):
        """Parse an AUTH message in either form.

        Supported wire formats:
            AUTH:<token>
            AUTH:<server_uuid>:<payload_uuid>:<token>

        Returns a dict describing the parsed message, or None on
        malformed input. The ``kind`` field is either ``'legacy'`` or
        ``'identity'``.
        """
        if not message or not message.startswith('AUTH:'):
            return None
        rest = message[5:].strip()
        parts = rest.split(':')
        if len(parts) == 1 and parts[0]:
            return {"kind": "legacy", "token": parts[0]}
        if len(parts) == 3 and all(parts):
            return {
                "kind": "identity",
                "server_uuid": parts[0],
                "payload_uuid": parts[1],
                "token": parts[2],
            }
        return None

    def get_valid_tokens(self):
        """Get all currently-valid tokens (current + grace)"""
        self._rotate_if_needed()
        current_window = self._window_number()
        
        tokens = []
        for offset in range(self.grace_windows + 1):
            window = current_window - offset
            tokens.append({
                'token': self._generate_for_window(window),
                'window': window,
                'expires_in': self._window_expires_in(window),
            })
        return tokens
    
    def _window_expires_in(self, window_num):
        """Seconds until a window expires"""
        now = time.time()
        expires_at = (window_num + self.grace_windows + 1) * self.rotation_seconds
        return max(0, int(expires_at - now))
    
    # ============================================
    # Static helpers
    # ============================================
    @staticmethod
    def generate_random(length=32):
        """Generate random token (for master secrets)"""
        return secrets.token_urlsafe(length)
    
    @staticmethod
    def hash_token(token):
        """Hash a token (for storage)"""
        return hashlib.sha256(token.encode()).hexdigest()
    
    @staticmethod
    def verify_hash(token, token_hash):
        """Verify token against hash"""
        return hmac.compare_digest(
            hashlib.sha256(token.encode()).hexdigest(),
            token_hash,
        )
    
    def __repr__(self):
        self._rotate_if_needed()
        return (
            f"Auth(rotation={self.rotation_seconds}s, "
            f"next_in={self.time_until_rotation}s)"
        )
