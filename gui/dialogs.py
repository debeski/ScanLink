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


# The approval window lists every site in full: a site cut off at the edge, or
# scrolled out of view, would be approved without the operator seeing it.
SITE_LIST_MAX_ROWS = 20
SITE_LIST_MIN_WIDTH = 40
SITE_LIST_MAX_WIDTH = 90


def site_list_size(sites):
    """``(rows, characters)`` for a listing that shows every site without scrolling when it fits."""
    rows = max(1, min(len(sites), SITE_LIST_MAX_ROWS))
    width = max([SITE_LIST_MIN_WIDTH, *(len(site) + 2 for site in sites)])
    return rows, min(width, SITE_LIST_MAX_WIDTH)


def _site_listing(parent, sites):
    rows, width = site_list_size(sites)
    holder = tk.Frame(parent)
    listing = tk.Listbox(holder, height=rows, width=width, activestyle=tk.NONE)
    for site in sites:
        listing.insert(tk.END, site)
    listing.grid(row=0, column=0, sticky="ew")
    if max(len(site) for site in sites) + 2 > width:
        scroll_x = tk.Scrollbar(holder, orient=tk.HORIZONTAL, command=listing.xview)
        listing.configure(xscrollcommand=scroll_x.set)
        scroll_x.grid(row=1, column=0, sticky="ew")
    if len(sites) > rows:
        scroll_y = tk.Scrollbar(holder, orient=tk.VERTICAL, command=listing.yview)
        listing.configure(yscrollcommand=scroll_y.set)
        scroll_y.grid(row=0, column=1, sticky="ns")
    holder.columnconfigure(0, weight=1)
    holder.pack(anchor=tk.W, fill=tk.X)
    return listing


def confirm_site_link(origin, other_sites, timeout_seconds, added_sites=None, cancel=None):
    """Ask whether ``origin`` may use the scanner: True, False, or None if unanswered.

    ``added_sites`` names what an already linked website's list gains; ``cancel``
    (a ``threading.Event``) closes the window unanswered when set.
    """
    if not _root:
        logging.error("GUI not initialized with root window")
        return None

    answer = {"value": None}
    dlg = tk.Toplevel()
    widening = bool(added_sites)
    dlg.title("Allow more websites to use ScanLink?" if widening else "Allow a website to use ScanLink?")
    dlg.resizable(False, False)

    frame = tk.Frame(dlg, padx=16, pady=14)
    frame.pack(fill=tk.BOTH, expand=True)
    tk.Label(frame, text=origin, font=("TkDefaultFont", 11, "bold"), wraplength=560, justify=tk.LEFT).pack(anchor=tk.W)
    if widening:
        tk.Label(
            frame,
            text="is already linked, and now asks to let these websites use the scanner on this computer too:",
            wraplength=560,
            justify=tk.LEFT,
        ).pack(anchor=tk.W)
        _site_listing(frame, list(added_sites))
        tk.Label(
            frame,
            text="If you choose Don't allow, it stays linked with the websites you allowed before.",
            wraplength=560,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(10, 0))
    else:
        tk.Label(frame, text="wants to use the scanner on this computer.", wraplength=560, justify=tk.LEFT).pack(anchor=tk.W)
        if other_sites:
            tk.Label(
                frame,
                text=f"Its administrator also allows these {len(other_sites)} websites:",
                wraplength=560,
                justify=tk.LEFT,
            ).pack(anchor=tk.W, pady=(10, 0))
            _site_listing(frame, list(other_sites))
    tk.Label(
        frame,
        text="Only allow websites you use for your work. You can unlink a website later from the ScanLink tray menu.",
        wraplength=560,
        justify=tk.LEFT,
    ).pack(anchor=tk.W, pady=(10, 0))

    def finish(value):
        answer["value"] = value
        if dlg.winfo_exists():
            dlg.destroy()

    def watch_cancel():
        if cancel is not None and cancel.is_set():
            finish(None)
        elif dlg.winfo_exists():
            dlg.after(200, watch_cancel)

    buttons = tk.Frame(frame)
    buttons.pack(pady=(14, 0))
    tk.Button(buttons, text="Allow", command=lambda: finish(True), width=12).pack(side=tk.LEFT, padx=8)
    deny = tk.Button(buttons, text="Don't allow", command=lambda: finish(False), width=12)
    deny.pack(side=tk.LEFT, padx=8)
    dlg.protocol("WM_DELETE_WINDOW", lambda: finish(False))
    dlg.bind("<Escape>", lambda event: finish(False))
    dlg.after(int(timeout_seconds * 1000), lambda: finish(None))
    if cancel is not None:
        dlg.after(200, watch_cancel)

    dlg.update_idletasks()
    width, height = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
    x = max((dlg.winfo_screenwidth() // 2) - (width // 2), 0)
    y = max((dlg.winfo_screenheight() // 2) - (height // 2), 0)
    dlg.geometry(f"+{x}+{y}")
    dlg.deiconify()
    dlg.wait_visibility()
    # Shown above other windows, but without taking the keyboard from what the
    # operator is typing in; "Don't allow" is the default once it is clicked.
    dlg.attributes("-topmost", True)
    dlg.lift()
    deny.focus_set()
    dlg.wait_window()
    return answer["value"]
