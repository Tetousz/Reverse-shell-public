#!/usr/bin/env python3
"""
Logging System
Writes to console + rotating file
"""
import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from pathlib import Path


class Logger:
    """Centralized logger"""
    
    _instance = None
    _loggers = {}
    
    def __new__(cls, name='rsc', log_dir='logs', level='INFO', max_size_mb=10):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._setup(name, log_dir, level, max_size_mb)
        return cls._instance
    
    def _setup(self, name, log_dir, level, max_size_mb):
        """Setup logging handlers"""
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        
        log_file = Path(log_dir) / f"{name}.log"
        max_bytes = max_size_mb * 1024 * 1024
        
        # Format
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s: %(message)s',
            datefmt='%H:%M:%S'
        )
        
        # File handler (rotating)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=3
        )
        file_handler.setFormatter(formatter)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        
        # Root logger
        self._root = logging.getLogger(name)
        self._root.setLevel(getattr(logging, level.upper(), logging.INFO))
        self._root.addHandler(file_handler)
        self._root.addHandler(console_handler)
    
    def get(self, module_name=None):
        """Get a child logger for a module"""
        if module_name:
            return self._root.getChild(module_name)
        return self._root
    
    @staticmethod
    def info(msg, module=None):
        Logger().get(module).info(msg)
    
    @staticmethod
    def error(msg, module=None):
        Logger().get(module).error(msg)
    
    @staticmethod
    def warning(msg, module=None):
        Logger().get(module).warning(msg)
    
    @staticmethod
    def debug(msg, module=None):
        Logger().get(module).debug(msg)
    
    @staticmethod
    def critical(msg, module=None):
        Logger().get(module).critical(msg)


# Module-level logger
def get_logger(module_name=None):
    """Get a logger for a module"""
    return Logger().get(module_name)
