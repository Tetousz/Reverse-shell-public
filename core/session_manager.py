#!/usr/bin/env python3
"""
Session Manager
Tracks all active reverse shell sessions
"""
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class Session:
    """A single reverse shell session"""
    id: int
    socket: object
    addr: tuple
    active: bool = True
    created: datetime = field(default_factory=datetime.now)
    channel: Optional[object] = None
    last_seen: float = field(default_factory=time.time)
    response_queue: queue.Queue = field(default_factory=queue.Queue)
    in_response: bool = False
    payload_uuid: object = None
    
    @property
    def address(self):
        return f"{self.addr[0]}:{self.addr[1]}"
    
    def touch(self):
        """Update last seen"""
        self.last_seen = time.time()
    
    def __repr__(self):
        status = "🟢" if self.active else "🔴"
        return f"{status} Session(#{self.id:04d}, {self.address})"


class SessionManager:
    """Thread-safe session manager"""
    
    def __init__(self):
        self._sessions = {}
        self._lock = threading.Lock()
        self._counter = 0
    
    # ============================================
    # CRUD
    # ============================================
    def add(self, socket, addr, channel=None):
        """Add a new session, returns session id"""
        with self._lock:
            self._counter += 1
            session_id = self._counter
            self._sessions[session_id] = Session(
                id=session_id,
                socket=socket,
                addr=addr,
                channel=channel,
            )
            return session_id
    
    def get(self, session_id):
        """Get a session by id"""
        with self._lock:
            return self._sessions.get(session_id)
    
    def get_by_socket(self, socket):
        """Get a session by socket"""
        with self._lock:
            for session in self._sessions.values():
                if session.socket == socket:
                    return session
        return None
    
    def remove(self, session_id):
        """Remove a session"""
        with self._lock:
            return self._sessions.pop(session_id, None)
    
    # ============================================
    # Queries
    # ============================================
    def all(self):
        """Get all sessions"""
        with self._lock:
            return list(self._sessions.values())
    
    def active(self):
        """Get active sessions"""
        with self._lock:
            return [s for s in self._sessions.values() if s.active]
    
    def inactive(self):
        """Get inactive sessions"""
        with self._lock:
            return [s for s in self._sessions.values() if not s.active]
    
    def count(self):
        """Total session count"""
        with self._lock:
            return len(self._sessions)
    
    def count_active(self):
        """Active session count"""
        return len(self.active())
    
    # ============================================
    # Status
    # ============================================
    def set_active(self, session_id, active):
        """Set session active status"""
        session = self.get(session_id)
        if session:
            session.active = active
            session.touch()
            return True
        return False
    
    def touch(self, session_id):
        """Update last seen"""
        session = self.get(session_id)
        if session:
            session.touch()
    
    def clear(self):
        """Remove all sessions"""
        with self._lock:
            self._sessions.clear()
    
    def __repr__(self):
        return f"SessionManager(total={self.count()}, active={self.count_active()})"
