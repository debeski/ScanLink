import argparse
import json
import os
import subprocess
import sys
import venv

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(ROOT_DIR, "VERSION")
DATA_SEPARATOR = ";" if os.name == "nt" else ":"
ARCH_CHOICES = ("both", "x64", "x86", "current")
REQUIRED_BUILD_MODULES = (
    ("PyInstaller", "pyinstaller"),
    ("flask", "Flask"),
    ("PIL", "Pillow"),
    ("reportlab", "reportlab"),
    ("pystray", "pystray"),
    ("requests", "requests"),
    ("twain", "pytwain"),
    ("cryptography", "cryptography"),
)


def read_version():
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as version_file:
            version = version_file.read().strip()
            if version:
                return version
    except OSError as exc:
        print(f"WARNING: Failed to read VERSION file at {VERSION_FILE}: {exc}")
    return "0.5.0"


APP_VERSION = read_version()

r"""
ScanLink build script.

Usage:
    python build_exe.py
    python build_exe.py --arch x64
    python build_exe.py --arch x86
    python build_exe.py --arch both --python-x64 C:\Python310\python.exe --python-x86 C:\Python310-32\python.exe

Output:
    dist/ScanLink_<version>_x64.exe
    dist/ScanLink_<version>_x86.exe
"""


REQUIREMENTS_FILE = os.path.join(ROOT_DIR, "requirements.txt")


def venv_dir(arch):
    return os.path.join(ROOT_DIR, f".venv-{arch}")


def venv_python(arch):
    return os.path.join(venv_dir(arch), "Scripts", "python.exe")


def ensure_venv(arch, base_python):
    venv_path = venv_dir(arch)
    python_exe = venv_python(arch)

    if not os.path.exists(python_exe):
        print(f"Creating {arch} venv at {venv_path} ...")
        subprocess.run([base_python, "-m", "venv", venv_path], check=True)
        print(f"{arch} venv created.")

    if os.path.exists(REQUIREMENTS_FILE):
        print(f"Installing requirements into {arch} venv ...")
        subprocess.run(
            [python_exe, "-m", "pip", "install", "--quiet", "-r", REQUIREMENTS_FILE],
            check=True,
        )
        print(f"{arch} requirements installed.")
    else:
        print(f"WARNING: {REQUIREMENTS_FILE} not found — skipping pip install.")

    return python_exe


def current_arch():
    return "x64" if sys.maxsize > 2 ** 32 else "x86"


def python_arch(python_executable):
    command = [
        python_executable,
        "-c",
        "import sys; print('x64' if sys.maxsize > 2**32 else 'x86')",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def missing_build_modules(python_executable):
    script = (
        "import importlib.util, json; "
        f"modules = {REQUIRED_BUILD_MODULES!r}; "
        "print(json.dumps([dist for module, dist in modules "
        "if importlib.util.find_spec(module) is None]))"
    )
    result = subprocess.run(
        [python_executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def parse_args():
    parser = argparse.ArgumentParser(description="Build ScanLink Windows executables.")
    parser.add_argument(
        "--arch",
        choices=ARCH_CHOICES,
        default=os.getenv("SCANLINK_BUILD_ARCH", "both"),
        help="Architecture to build. Default: both.",
    )
    parser.add_argument(
        "--python-x64",
        default=os.getenv("SCANLINK_PYTHON_X64"),
        help="64-bit Python executable to use when building x64.",
    )
    parser.add_argument(
        "--python-x86",
        default=os.getenv("SCANLINK_PYTHON_X86"),
        help="32-bit Python executable to use when building x86.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the PyInstaller commands without executing them.",
    )
    return parser.parse_args()


def resolve_requested_arches(requested_arch):
    if requested_arch == "both":
        return ["x64", "x86"]
    if requested_arch == "current":
        return [current_arch()]
    return [requested_arch]


def resolve_python_for_arch(arch, args):
    configured_python = args.python_x64 if arch == "x64" else args.python_x86
    if configured_python:
        return configured_python
    if arch == current_arch():
        return sys.executable
    return None


def add_data_arg(source, destination="."):
    return f"--add-data={source}{DATA_SEPARATOR}{destination}"


def build_pyinstaller_args(build_name):
    pyinstaller_args = [
        "main.py",
        "--onefile",
        "--noconsole",
        f"--name={build_name}",
        "--clean",
        "--hidden-import=gui",
        "--hidden-import=gui.dialogs",
        "--hidden-import=PIL",
        "--hidden-import=PIL.Image",
        "--hidden-import=PIL.ImageDraw",
        "--hidden-import=protocol_handler",
        "--hidden-import=flask",
        "--hidden-import=werkzeug",
        "--hidden-import=jinja2",
        "--hidden-import=itsdangerous",
        "--hidden-import=click",
        "--hidden-import=blinker",
        "--collect-all=flask",
        "--collect-all=werkzeug",
        "--collect-all=jinja2",
    ]

    if os.path.exists("README.md"):
        pyinstaller_args.append(add_data_arg("README.md"))

    if os.path.exists("VERSION"):
        pyinstaller_args.append(add_data_arg("VERSION"))

    if os.path.exists("app_icon.ico"):
        pyinstaller_args.append("--icon=app_icon.ico")
        pyinstaller_args.append(add_data_arg("app_icon.ico"))

    return pyinstaller_args


def build_arch(arch, python_executable, dry_run=False):
    build_name = f"ScanLink_{APP_VERSION}_{arch}"
    pyinstaller_args = build_pyinstaller_args(build_name)
    command = [python_executable, "-m", "PyInstaller", *pyinstaller_args]

    print(f"Building {build_name}.exe with {python_executable}...")
    print(f"Arguments: {' '.join(command)}")
    print()

    if dry_run:
        return

    subprocess.run(command, cwd=ROOT_DIR, check=True)
    print()
    print(f"Build complete! Output: dist/{build_name}.exe")
    print()


def main():
    args = parse_args()
    requested_arches = resolve_requested_arches(args.arch)
    python_by_arch = {}

    for arch in requested_arches:
        python_executable = resolve_python_for_arch(arch, args)
        if not python_executable:
            raise SystemExit(
                f"Cannot build {arch}: provide --python-{arch} or set "
                f"SCANLINK_PYTHON_{arch.upper()} to a {arch} Python executable."
            )
        detected_arch = python_arch(python_executable)
        if detected_arch != arch:
            raise SystemExit(
                f"Cannot build {arch}: Python executable '{python_executable}' is {detected_arch}."
            )
        venv_py = ensure_venv(arch, python_executable)
        missing_modules = missing_build_modules(venv_py)
        if missing_modules:
            missing_list = ", ".join(missing_modules)
            raise SystemExit(
                f"Cannot build {arch}: missing packages in venv: {missing_list}.\n"
                f"Check that all entries are in requirements.txt."
            )
        python_by_arch[arch] = venv_py

    for arch in requested_arches:
        build_arch(arch, python_by_arch[arch], dry_run=args.dry_run)

    print("Next steps:")
    print("1. Compile setup.iss with Inno Setup or update it for the new x86/x64 executable names")
    print("2. Run the installer on a Windows machine")
    print("3. Use the installed static/scanlink.js client or the shared Microsys helper in your Django project")


if __name__ == "__main__":
    main()
