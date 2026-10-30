#!/usr/bin/env python3
"""
Theme - Color schemes for the dashboard
"""


class Theme:
    """Color theme manager"""
    
    DARK = {
        'bg_primary': '#0a0a1a',
        'bg_secondary': '#12122a',
        'bg_tertiary': '#1a1a3e',
        'bg_input': '#0d0d1f',
        'bg_hover': '#3a2a5e',
        'bg_listbox': '#12122a',
        'text_primary': '#e8e0f0',
        'text_secondary': '#b8a8d0',
        'text_muted': '#7a6a9a',
        'text_listbox': '#e8e0f0',
        'accent_primary': '#7c3aed',
        'accent_secondary': '#6d28d9',
        'accent_light': '#a78bfa',
        'accent_cyan': '#06b6d4',
        'success': '#10b981',
        'warning': '#f59e0b',
        'error': '#ef4444',
        'terminal_bg': '#05050f',
        'terminal_green': '#34d399',
        'border': '#2a1a4e',
        'menu_bg': '#1a1a3e',
        'menu_fg': '#e8e0f0',
        'menu_active_bg': '#3a2a5e',
        'menu_active_fg': '#ffffff',
        'notes_bg': '#0d0d1f',
        'notes_fg': '#e8e0f0',
    }
    
    LIGHT = {
        'bg_primary': '#f0ecf8',
        'bg_secondary': '#e8e0f5',
        'bg_tertiary': '#ddd0f0',
        'bg_input': '#f5f0fa',
        'bg_hover': '#b8a0d8',
        'bg_listbox': '#e8e0f5',
        'text_primary': '#1a0a2a',
        'text_secondary': '#3a2a5a',
        'text_muted': '#7a6a9a',
        'text_listbox': '#1a0a2a',
        'accent_primary': '#6d28d9',
        'accent_secondary': '#5b21b6',
        'accent_light': '#8b5cf6',
        'accent_cyan': '#0891b2',
        'success': '#059669',
        'warning': '#d97706',
        'error': '#dc2626',
        'terminal_bg': '#f5f0fa',
        'terminal_green': '#059669',
        'border': '#c4b0e0',
        'menu_bg': '#e8e0f5',
        'menu_fg': '#1a0a2a',
        'menu_active_bg': '#c4b0e0',
        'menu_active_fg': '#1a0a2a',
        'notes_bg': '#f5f0fa',
        'notes_fg': '#1a0a2a',
    }
    
    THEMES = {'dark': DARK, 'light': LIGHT}
    
    def __init__(self, name='dark'):
        self.current = name
        self.colors = self.THEMES.get(name, self.DARK)
    
    def get(self, key, default='#000000'):
        """Get a color by key"""
        return self.colors.get(key, default)
    
    def toggle(self):
        """Toggle between dark and light"""
        self.current = 'light' if self.current == 'dark' else 'dark'
        self.colors = self.THEMES[self.current]
        return self.current
    
    def __getitem__(self, key):
        return self.get(key)
