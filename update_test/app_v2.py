"""Tiny test app — VERSION 2. This is the "new version" after the update."""
import tkinter as tk
import os, sys

root = tk.Tk()
root.title("Update Test App")
root.geometry("400x200")
root.resizable(False, False)
root.configure(bg="#1e1e2e")

tk.Label(root, text="VERSION 2 ✓", font=("Arial", 32, "bold"),
         bg="#1e1e2e", fg="#a6e3a1").pack(pady=20)

tk.Label(root, text=f"Running from:\n{sys.executable}",
         font=("Arial", 9), bg="#1e1e2e", fg="#6c7086",
         wraplength=380, justify="center").pack()

tk.Label(root, text="Update successful! This is the new version.",
         font=("Arial", 9, "italic"), bg="#1e1e2e", fg="#a6e3a1").pack(pady=10)

root.mainloop()
