#!/usr/bin/env python3
"""
Discovery - Auto-find ngrok tunnel
Scans ngrok subdomains (1.tcp.eu.ngrok.io, 2.tcp.eu.ngrok.io, ...)
and tests which one points to our server
"""
import socket
import subprocess
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


class Discovery:
    """Auto-discovers ngrok server address"""
    
    # Default ranges
    DEFAULT_PREFIX = "tcp.eu.ngrok.io"
    DEFAULT_PORT = 16021
    DEFAULT_MAX_DOMAINS = 50
    DEFAULT_MAX_WORKERS = 10
    DEFAULT_TIMEOUT = 3.0
    
    def __init__(
        self,
        auth_token,
        port=4444,
        prefix=None,
        max_domains=None,
    ):
        self.auth_token = auth_token
        self.port = port
        self.prefix = prefix or self.DEFAULT_PREFIX
        self.max_domains = max_domains or self.DEFAULT_MAX_DOMAINS
        self.timeout = self.DEFAULT_TIMEOUT
    
    # ============================================
    # DNS resolution
    # ============================================
    def _resolve_ips(self, domain, use_google_dns=True):
        """
        Resolve domain to IPs.
        Uses nslookup with Google DNS to avoid hijacking.
        """
        try:
            args = ['nslookup', domain]
            if use_google_dns:
                args.append('8.8.8.8')
            
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=5,
            )
            
            output = result.stdout + result.stderr
            ip_pattern = r'Address:\s*(\d+\.\d+\.\d+\.\d+)'
            matches = re.findall(ip_pattern, output)
            
            # Filter out DNS servers
            dns_servers = {'8.8.8.8', '8.8.4.4', '1.1.1.1', '1.0.0.1'}
            ips = [ip for ip in matches if ip not in dns_servers]
            
            # Remove duplicates, keep order
            seen = set()
            unique_ips = []
            for ip in ips:
                if ip not in seen:
                    seen.add(ip)
                    unique_ips.append(ip)
            
            return unique_ips
            
        except Exception:
            return []
    
    # ============================================
    # Connection test
    # ============================================
    def _test_connection(self, ip, port=None):
        """
        Test if server responds correctly.
        Returns (ip, port, response) or None.
        """
        port = port or self.port
        
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((ip, port))
            
            # Send auth
            sock.send(f"AUTH:{self.auth_token}\n".encode())
            
            # Read response
            sock.settimeout(2.0)
            response = sock.recv(1024).decode(errors='ignore').strip()
            sock.close()
            
            if response == "AUTH_SUCCESS":
                return (ip, port, response)
            return None
            
        except (socket.timeout, ConnectionRefusedError, OSError):
            return None
    
    # ============================================
    # Domain scanning
    # ============================================
    def _check_domain(self, num):
        """
        Check a single domain number.
        Returns (ip, port) if valid server found, else None.
        """
        domain = f"{num}.{self.prefix}"
        
        # Resolve to IPs
        ips = self._resolve_ips(domain)
        if not ips:
            return None, domain
        
        # Test each IP
        for ip in ips:
            result = self._test_connection(ip, self.port)
            if result:
                return result[:2], domain  # (ip, port), domain
        
        return None, domain
    
    # ============================================
    # Main discovery
    # ============================================
    def scan(self, callback=None):
        """
        Scan for the server.
        
        Args:
            callback: optional callback(domain, status, result)
                      status = 'checking' | 'found' | 'failed'
        
        Returns:
            (host, port) or None
        """
        return self.scan_parallel(callback)
    
    def scan_parallel(self, callback=None):
        """Scan multiple domains in parallel"""
        with ThreadPoolExecutor(max_workers=self.DEFAULT_MAX_WORKERS) as executor:
            futures = {
                executor.submit(self._check_domain, num): num
                for num in range(1, self.max_domains + 1)
            }
            
            for future in as_completed(futures):
                result, domain = future.result()
                
                if result:
                    if callback:
                        callback(domain, 'found', result)
                    # Cancel remaining tasks
                    for f in futures:
                        f.cancel()
                    return result
                else:
                    if callback:
                        callback(domain, 'failed', None)
        
        return None
    
    def scan_sequential(self, callback=None):
        """Scan domains sequentially (slower but simpler)"""
        for num in range(1, self.max_domains + 1):
            domain = f"{num}.{self.prefix}"
            
            if callback:
                callback(domain, 'checking', None)
            
            result, domain = self._check_domain(num)
            
            if result:
                if callback:
                    callback(domain, 'found', result)
                return result
            else:
                if callback:
                    callback(domain, 'failed', None)
        
        return None
    
    # ============================================
    # Public: auto-find
    # ============================================
    def find(self, callback=None, verbose=True):
        """
        Find the server, tries localhost first.
        
        Returns:
            (host, port) or None
        """
        # Try localhost first (fast path for same network)
        if verbose and callback:
            callback('localhost', 'checking', None)
        
        result = self._test_connection('127.0.0.1', self.port)
        if result:
            if verbose and callback:
                callback('localhost', 'found', result[:2])
            return result[:2]
        
        if verbose and callback:
            callback('localhost', 'failed', None)
        
        # Then scan ngrok
        return self.scan(callback)


def find_server(auth_token, port=4444, callback=None):
    """Convenience function"""
    discovery = Discovery(auth_token, port)
    return discovery.find(callback)
