#!/usr/bin/env python3
"""
Dashboard entry point
"""
import tkinter as tk
from dashboard.dashboard import Dashboard


def main():
    root = tk.Tk()
    app = Dashboard(root)
    root.mainloop()


if __name__ == "__main__":
    main()
