import tkinter as tk
from tkinter import simpledialog, messagebox
import logging

# Global reference to root
_root = None

def init_gui(root_window):
    global _root
    _root = root_window

def select_scanner_dialog(sources):
    """
    Shows a custom TopMost dialog to select a scanner.
    Returns {'name': selected_source_name, 'default': is_default_checked} or None
    """
    if not _root:
        logging.error("GUI not initialized with root window")
        return None

    selection = {'name': None, 'default': False}
    
    # Create Toplevel instead of Tk
    dlg = tk.Toplevel(_root)
    dlg.title("Select Scanner")
    
    # Bring to front
    dlg.attributes('-topmost', True)
    dlg.focus_force()
    
    # Center
    width = 400
    height = 350
    screen_width = dlg.winfo_screenwidth()
    screen_height = dlg.winfo_screenheight()
    x = (screen_width // 2) - (width // 2)
    y = (screen_height // 2) - (height // 2)
    dlg.geometry(f'{width}x{height}+{x}+{y}')
    
    # Modal behavior
    dlg.transient(_root)
    dlg.grab_set()

    lbl = tk.Label(dlg, text="Choose your scanner:")
    lbl.pack(pady=10)

    listbox = tk.Listbox(dlg, selectmode=tk.SINGLE)
    for s in sources:
        listbox.insert(tk.END, s)
    listbox.pack(expand=True, fill=tk.BOTH, padx=20)
    
    if sources:
        listbox.selection_set(0)

    var_default = tk.BooleanVar()
    chk = tk.Checkbutton(dlg, text="Set as default scanner", variable=var_default)
    chk.pack(pady=10)

    def on_select():
        cur = listbox.curselection()
        if cur:
            selection['name'] = sources[cur[0]]
            selection['default'] = var_default.get()
            dlg.destroy()
        else:
            messagebox.showwarning("Warning", "Please select a scanner.", parent=dlg)

    def on_cancel():
        dlg.destroy()

    btn_frame = tk.Frame(dlg)
    btn_frame.pack(pady=10)
    
    tk.Button(btn_frame, text="Select", command=on_select, width=10).pack(side=tk.LEFT, padx=10)
    tk.Button(btn_frame, text="Cancel", command=on_cancel, width=10).pack(side=tk.LEFT, padx=10)
    
    # Wait for window to close
    _root.wait_window(dlg)
    
    if selection['name']:
        return selection
    return None
