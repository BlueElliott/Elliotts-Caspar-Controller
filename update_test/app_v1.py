"""Tiny test app — VERSION 1. Simulates the running application."""
import tkinter as tk
import os, sys

root = tk.Tk()
root.title("Update Test App")
root.geometry("400x200")
root.resizable(False, False)
root.configure(bg="#1e1e2e")

tk.Label(root, text="VERSION 1", font=("Arial", 32, "bold"),
         bg="#1e1e2e", fg="#f38ba8").pack(pady=20)

tk.Label(root, text=f"Running from:\n{sys.executable}",
         font=("Arial", 9), bg="#1e1e2e", fg="#6c7086",
         wraplength=380, justify="center").pack()

tk.Label(root, text="Close this window to simulate the app shutting down.",
         font=("Arial", 9, "italic"), bg="#1e1e2e", fg="#45475a").pack(pady=10)

root.mainloop()
