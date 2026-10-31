"""Manages the Ngrok subprocess lifecycle and captures its public URL."""

import subprocess
import re
import threading
import time
import os
import queue
import shutil


class NgrokManager:
    def __init__(self, port=4444, binary_path="ngrok", region="eu"):
        self.port = port
        self.binary_path = binary_path
        self.region = region
        self.process = None
        self.public_url = None
        self._stop_event = threading.Event()
        self._q = None
        self._reader_thread = None

    def _resolve_binary(self):
        """Find the ngrok binary, checking local folder first, then system PATH."""
        # 1. Check local folder (e.g., ./ngrok)
        if os.path.exists(self.binary_path):
            return os.path.abspath(self.binary_path)
        
        # 2. Check system PATH (e.g., installed via pacman/apt)
        system_path = shutil.which("ngrok")
        if system_path:
            return system_path

        return None

    def start(self):
        if self.process and self.public_url:
            return True

        if self.process:
            self.stop()

        resolved_bin = self._resolve_binary()
        if not resolved_bin:
            print("[-] Ngrok binary not found in project folder or system PATH.")
            print("[-] Install it via your package manager (e.g., 'sudo pacman -S ngrok') or place it in the root folder.")
            return False

        self._stop_event.clear()
        self.public_url = None
        self._q = queue.Queue()

        cmd = [
            resolved_bin, "tcp", str(self.port),
            f"--region={self.region}",
            "--log=stdout",
            "--log-format=logfmt",
        ]

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            print(f"[-] Failed to launch Ngrok: {e}")
            self.process = None
            return False

        print(f"[*] Waiting for Ngrok to assign URL (Region: {self.region})...")
        self._reader_thread = threading.Thread(target=self._reader, daemon=True)
        self._reader_thread.start()

        url_pattern = re.compile(r"url=(tcp://[^\s]+)")
        deadline = time.time() + 12

        while time.time() < deadline:
            if self.process.poll() is not None:
                print("[-] Ngrok process exited early.")
                self.process = None
                return False

            try:
                line = self._q.get(timeout=0.1)
            except queue.Empty:
                continue

            match = url_pattern.search(line)
            if match:
                full_url = match.group(1)
                self.public_url = full_url.replace("tcp://", "")
                print(f"[+] Ngrok tunnel established: tcp://{self.public_url}")
                return True

        print("[-] Ngrok timeout: no URL in output within 12s")
        self.stop()
        return False

    def _reader(self):
        try:
            for line in self.process.stdout:
                if self._stop_event.is_set():
                    break
                self._q.put(line)
        except Exception:
            pass

    def stop(self):
        if self.process:
            self._stop_event.set()
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
            except Exception:
                pass
            self.process = None
            self.public_url = None
            print("[*] Ngrok tunnel stopped")
