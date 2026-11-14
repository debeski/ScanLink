import tkinter as tk
from tkinter import messagebox
from tkinter import scrolledtext
import logging

# Global reference to root
_root = None

def init_gui(root_window):
    global _root
    _root = root_window

def get_gui_root():
    return _root

def select_scanner_dialog(sources):
    """
    Shows a custom TopMost dialog to select a scanner.
    Returns {'name': selected_source_name, 'default': is_default_checked} or None
    """
    if not _root:
        logging.error("GUI not initialized with root window")
        return None

    selection = {'name': None, 'default': False}

    # Use a standalone top-level window instead of a transient child of the
    # hidden tray root. The transient/withdrawn-root combination was causing
    # the chooser to flash or disappear on some client machines.
    dlg = tk.Toplevel()
    dlg.title("Select Scanner")
    dlg.resizable(False, False)
    dlg.protocol("WM_DELETE_WINDOW", lambda: on_cancel())
    
    width = 400
    height = 350
    screen_width = dlg.winfo_screenwidth()
    screen_height = dlg.winfo_screenheight()
    x = (screen_width // 2) - (width // 2)
    y = (screen_height // 2) - (height // 2)
    dlg.geometry(f'{width}x{height}+{x}+{y}')

    lbl = tk.Label(dlg, text="Choose your scanner:")
    lbl.pack(pady=10)

    listbox = tk.Listbox(dlg, selectmode=tk.SINGLE)
    for s in sources:
        listbox.insert(tk.END, s)
    listbox.pack(expand=True, fill=tk.BOTH, padx=20)
    
    if sources:
        listbox.selection_set(0)
        listbox.activate(0)
        listbox.focus_set()

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
    
    dlg.update_idletasks()
    dlg.deiconify()
    dlg.wait_visibility()
    dlg.attributes('-topmost', True)
    dlg.lift()
    dlg.focus_force()
    dlg.grab_set()
    dlg.wait_window()
    
    if selection['name']:
        return selection
    return None


def show_text_dialog(title, body, width=760, height=520):
    if not _root:
        logging.error("GUI not initialized with root window")
        return

    dlg = tk.Toplevel()
    dlg.title(title)
    dlg.resizable(True, True)
    dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)

    screen_width = dlg.winfo_screenwidth()
    screen_height = dlg.winfo_screenheight()
    x = max((screen_width // 2) - (width // 2), 0)
    y = max((screen_height // 2) - (height // 2), 0)
    dlg.geometry(f"{width}x{height}+{x}+{y}")

    frame = tk.Frame(dlg, padx=12, pady=12)
    frame.pack(fill=tk.BOTH, expand=True)

    text = scrolledtext.ScrolledText(frame, wrap=tk.WORD)
    text.pack(fill=tk.BOTH, expand=True)
    text.insert("1.0", body)
    text.configure(state=tk.DISABLED)

    close_button = tk.Button(frame, text="Close", command=dlg.destroy, width=12)
    close_button.pack(pady=(10, 0))

    dlg.update_idletasks()
    dlg.deiconify()
    dlg.wait_visibility()
    dlg.attributes("-topmost", True)
    dlg.lift()
    dlg.focus_force()
    dlg.grab_set()
    dlg.wait_window()


def confirm_site_link(origin, other_sites, timeout_seconds):
    """Ask whether ``origin`` may use the scanner: True, False, or None if unanswered."""
    if not _root:
        logging.error("GUI not initialized with root window")
        return None

    answer = {"value": None}
    dlg = tk.Toplevel()
    dlg.title("Allow a website to use ScanLink?")
    dlg.resizable(False, False)

    frame = tk.Frame(dlg, padx=16, pady=14)
    frame.pack(fill=tk.BOTH, expand=True)
    tk.Label(frame, text=origin, font=("TkDefaultFont", 11, "bold"), wraplength=440, justify=tk.LEFT).pack(anchor=tk.W)
    tk.Label(frame, text="wants to use the scanner on this computer.", wraplength=440, justify=tk.LEFT).pack(anchor=tk.W)
    if other_sites:
        tk.Label(
            frame,
            text="Its administrator also allows these websites:",
            wraplength=440,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(10, 0))
        listing = tk.Listbox(frame, height=min(len(other_sites), 6), width=56)
        for site in other_sites:
            listing.insert(tk.END, site)
        listing.pack(anchor=tk.W, fill=tk.X)
    tk.Label(
        frame,
        text="Only allow a website you use for your work. You can unlink it later from the ScanLink tray menu.",
        wraplength=440,
        justify=tk.LEFT,
    ).pack(anchor=tk.W, pady=(10, 0))

    def finish(value):
        answer["value"] = value
        if dlg.winfo_exists():
            dlg.destroy()

    buttons = tk.Frame(frame)
    buttons.pack(pady=(14, 0))
    tk.Button(buttons, text="Allow", command=lambda: finish(True), width=12).pack(side=tk.LEFT, padx=8)
    deny = tk.Button(buttons, text="Don't allow", command=lambda: finish(False), width=12)
    deny.pack(side=tk.LEFT, padx=8)
    dlg.protocol("WM_DELETE_WINDOW", lambda: finish(False))
    dlg.bind("<Escape>", lambda event: finish(False))
    dlg.after(int(timeout_seconds * 1000), lambda: finish(None))

    dlg.update_idletasks()
    width, height = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
    x = max((dlg.winfo_screenwidth() // 2) - (width // 2), 0)
    y = max((dlg.winfo_screenheight() // 2) - (height // 2), 0)
    dlg.geometry(f"+{x}+{y}")
    dlg.deiconify()
    dlg.wait_visibility()
    dlg.attributes("-topmost", True)
    dlg.lift()
    dlg.focus_force()
    deny.focus_set()
    dlg.grab_set()
    dlg.wait_window()
    return answer["value"]
