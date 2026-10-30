#!/usr/bin/env python3
"""
Sidebar - Connection list widget
"""
import tkinter as tk
from tkinter import ttk


class Sidebar:
    """Sidebar with session list"""
    
    def __init__(self, parent, theme, on_select=None):
        self.parent = parent
        self.theme = theme
        self.on_select = on_select
        
        # Main frame
        self.frame = tk.Frame(parent, bg=theme['bg_primary'], width=280)
        self.frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 8))
        self.frame.pack_propagate(False)
        
        # Title
        self.title = tk.Label(
            self.frame,
            text="📡 Sessions",
            font=('Segoe UI', 12, 'bold'),
            fg=theme['accent_light'],
            bg=theme['bg_primary'],
        )
        self.title.pack(fill=tk.X, pady=(0, 8))
        
        # Session counter
        self.counter_label = tk.Label(
            self.frame,
            text="0 active / 0 total",
            font=('Segoe UI', 9),
            fg=theme['text_muted'],
            bg=theme['bg_primary'],
        )
        self.counter_label.pack(fill=tk.X, pady=(0, 8))
        
        # Listbox container
        list_container = tk.Frame(self.frame, bg=theme['bg_primary'])
        list_container.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = tk.Scrollbar(
            list_container,
            orient=tk.VERTICAL,
            bg=theme['bg_secondary'],
            troughcolor=theme['bg_primary'],
        )
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.listbox = tk.Listbox(
            list_container,
            font=('Consolas', 10),
            bg=theme['bg_listbox'],
            fg=theme['text_listbox'],
            selectbackground=theme['accent_primary'],
            selectforeground='#ffffff',
            borderwidth=0,
            highlightthickness=0,
            activestyle='none',
            yscrollcommand=scrollbar.set,
        )
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.listbox.yview)
        
        self.listbox.bind('<<ListboxSelect>>', self._on_select)
        
        # Buttons
        btn_frame = tk.Frame(self.frame, bg=theme['bg_primary'])
        btn_frame.pack(fill=tk.X, pady=(8, 0))
        
        self.refresh_btn = self._make_button(
            btn_frame, "🔄 Refresh", self._on_refresh
        )
        self.refresh_btn.pack(side=tk.LEFT, padx=2, fill=tk.X, expand=True)
    
    def _make_button(self, parent, text, command):
        """Create a themed button"""
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=self.theme['bg_tertiary'],
            fg=self.theme['text_primary'],
            activebackground=self.theme['bg_hover'],
            activeforeground=self.theme['text_primary'],
            relief='flat',
            padx=8,
            pady=5,
            font=('Segoe UI', 9),
            cursor='hand2',
        )
    
    def _on_select(self, event):
        """Handle session selection"""
        if self.on_select:
            selection = self.listbox.curselection()
            if selection:
                self.on_select(selection[0])
    
    def _on_refresh(self):
        """Refresh callback placeholder"""
        pass
    
    def update_sessions(self, sessions):
        """Update the session list"""
        self.listbox.delete(0, tk.END)
        
        active = sum(1 for s in sessions if s.active)
        total = len(sessions)
        self.counter_label.config(text=f"{active} active / {total} total")
        
        if not sessions:
            self.listbox.insert(tk.END, "  No active connections")
            return
        
        for session in sessions:
            status = "🟢" if session.active else "🔴"
            display = f" {status} #{session.id:04d} {session.address}"
            self.listbox.insert(tk.END, display)
    
    def get_selected_index(self):
        """Get selected index"""
        selection = self.listbox.curselection()
        return selection[0] if selection else None
