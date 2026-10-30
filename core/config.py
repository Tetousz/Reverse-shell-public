#!/usr/bin/env python3
"""
Configuration Management
Loads settings from file + environment variables
"""
import os
import json
from pathlib import Path


class Config:
    """Centralized configuration"""
    
    DEFAULTS = {
        'server': {
            'host': '0.0.0.0',
            'port': 4444,
            'auth_secret': 'SHELL_ACCESS_2024',
            'ngrok_url': None,
            'rotation_seconds': 3600,
            'grace_windows': 1,
        },
        'logging': {
            'level': 'INFO',
            'log_dir': 'logs',
            'max_size_mb': 10,
        },
        'dashboard': {
            'theme': 'dark',
            'window_width': 1300,
            'window_height': 750,
        },
        'exporter': {
            'output_dir': 'builds',
        },
    }
    
    def __init__(self, config_file='config.json'):
        self.config_file = Path(config_file)
        self._data = self._load()
    
    def _load(self):
        data = self._deep_copy(self.DEFAULTS)
        
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    file_data = json.load(f)
                data = self._merge(data, file_data)
            except (json.JSONDecodeError, IOError) as e:
                print(f"[!] Config load error: {e}")
        
        data = self._apply_env(data)
        return data
    
    def _apply_env(self, data):
        env_map = {
            'RSC_SERVER_HOST': ('server', 'host'),
            'RSC_SERVER_PORT': ('server', 'port', int),
            'RSC_AUTH_SECRET': ('server', 'auth_secret'),
            'RSC_ROTATION_SECONDS': ('server', 'rotation_seconds', int),
            'RSC_LOG_LEVEL': ('logging', 'level'),
            'RSC_DASHBOARD_THEME': ('dashboard', 'theme'),
        }
        
        for env_key, spec in env_map.items():
            value = os.environ.get(env_key)
            if value is not None:
                section, key = spec[0], spec[1]
                convert = spec[2] if len(spec) > 2 else str
                try:
                    data[section][key] = convert(value)
                except (ValueError, TypeError):
                    pass
        
        return data
    
    def _merge(self, base, override):
        result = self._deep_copy(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge(result[key], value)
            else:
                result[key] = value
        return result
    
    def _deep_copy(self, d):
        return json.loads(json.dumps(d))
    
    # ============================================
    # Accessors
    # ============================================
    def get(self, section, key, default=None):
        return self._data.get(section, {}).get(key, default)
    
    @property
    def host(self):
        return self.get('server', 'host')
    
    @property
    def port(self):
        return self.get('server', 'port')
    
    @property
    def auth_secret(self):
        """Master secret (server-only)"""
        return self.get('server', 'auth_secret')
    
    @property
    def auth_token(self):
        """Backward-compat alias for auth_secret"""
        return self.auth_secret
    
    @property
    def rotation_seconds(self):
        return self.get('server', 'rotation_seconds', 3600)
    
    @property
    def grace_windows(self):
        return self.get('server', 'grace_windows', 1)
    
    @property
    def theme(self):
        return self.get('dashboard', 'theme')
    
    def save(self):
        with open(self.config_file, 'w') as f:
            json.dump(self._data, f, indent=4)
        return True
    
    def __repr__(self):
        return (
            f"Config(host={self.host}, port={self.port}, "
            f"rotation={self.rotation_seconds}s)"
        )
