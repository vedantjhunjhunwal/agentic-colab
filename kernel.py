"""Execution kernels for notebooks.

Each open notebook gets one :class:`Kernel` that holds persistent state:

* a Python namespace (variables survive from cell to cell, like Colab's runtime)
* a separate AIDL environment (AIDL variables also persist across cells)

A cell run returns a structured result the frontend can render:
``{status, stdout, result, images, error}``.

Inline matplotlib figures are captured automatically and returned as
base64-encoded PNGs, so plots show up under the cell just like Colab.
"""
from __future__ import annotations

import ast
import base64
import importlib
import io
import os
import re
import shlex
import subprocess
import sys
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Dict, Optional

# Force a headless matplotlib backend before pyplot is ever imported.
os.environ.setdefault("MPLBACKEND", "Agg")

# Make the ``aidl`` package importable regardless of CWD.
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from aidl import AIDLError, Interpreter as AIDLInterpreter  # noqa: E402

# Line magics that we accept but treat as no-ops (Colab/IPython compatibility).
_NOOP_MAGICS = {
    "matplotlib", "env", "load_ext", "reload_ext", "autoreload", "config",
    "who", "whos", "lsmagic", "precision", "colors", "logstart", "logstop",
    "store", "alias", "pylab",
}


def _aidl_shell(cmd: str, timeout: int = 1800):
    """Run a shell command (used for ``!cmd`` / ``%pip`` lines), echo output.

    For pip/conda installs, refreshes sys.path so the newly installed package
    is immediately importable in the same kernel session.
    """
    try:
        proc = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout,
        )
        if proc.stdout:
            sys.stdout.write(proc.stdout)
        if proc.stderr:
            sys.stdout.write(proc.stderr)
        importlib.invalidate_caches()
        # After any pip/conda install, reload site-packages paths so the
        # new package can be imported in the current process without restart.
        cmd_lower = cmd.lower()
        if ("install" in cmd_lower and
                any(k in cmd_lower for k in ("pip", "conda", "-m pip"))):
            _refresh_import_paths()
        if proc.returncode != 0:
            sys.stdout.write(f"\n[exit code {proc.returncode}]\n")
    except subprocess.TimeoutExpired:
        sys.stdout.write(f"\n[command timed out after {timeout}s]\n")
    except Exception as exc:  # noqa: BLE001
        sys.stdout.write(f"\n[shell error: {exc}]\n")
    return None


def _refresh_import_paths():
    """Add any new site-packages directories to sys.path so freshly-installed
    packages are importable in the same Python process immediately."""
    import site
    try:
        for p in site.getsitepackages():
            if p not in sys.path:
                sys.path.insert(1, p)
    except Exception:
        pass
    try:
        user_site = site.getusersitepackages()
        if user_site not in sys.path:
            sys.path.insert(1, user_site)
    except Exception:
        pass
    importlib.invalidate_caches()


def _aidl_pip(arg_string: str, timeout: int = 3600):
    """Run pip as ``[sys.executable, '-m', 'pip', ...]`` WITHOUT a shell.

    Running without a shell avoids the Windows cmd.exe quote-mangling that
    breaks when the Python path contains spaces (e.g. C:\\Users\\First Last\\...).
    After a successful install, sys.path is refreshed so the new package is
    importable immediately in the same kernel.
    """
    try:
        args = shlex.split(arg_string, posix=(os.name != "nt"))
    except Exception:
        args = arg_string.split()
    cmd = [sys.executable, "-m", "pip"] + args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (proc.stdout or "") + (proc.stderr or "")
        if out:
            sys.stdout.write(out)
        importlib.invalidate_caches()
        if any(a in ("install", "uninstall") for a in args):
            _refresh_import_paths()
        if proc.returncode != 0:
            sys.stdout.write(f"\n[pip exited with code {proc.returncode}]\n")
            _pip_failure_hint(out)
    except subprocess.TimeoutExpired:
        sys.stdout.write(f"\n[pip timed out after {timeout}s]\n")
    except Exception as exc:  # noqa: BLE001
        sys.stdout.write(f"\n[pip error: {exc}]\n")
    return None


def _pip_failure_hint(output: str):
    """Turn common cryptic Windows pip failures into actionable guidance."""
    low = output.lower()
    hints = []
    if "enable-long-paths" in low or "long path" in low or \
       ("no such file or directory" in low and "site-packages" in low):
        hints.append(
            "This looks like the Windows 260-character PATH limit (common with large "
            "packages like torch).\n"
            "  Fix option 1 — enable Long Path support (recommended), then RESTART Windows:\n"
            "     • Open PowerShell as Administrator and run:\n"
            "       Set-ItemProperty -Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\FileSystem' "
            "-Name 'LongPathsEnabled' -Value 1\n"
            "  Fix option 2 — use python.org Python instead of the Microsoft Store build\n"
            "     (its install path is short, e.g. C:\\Python311\\, which avoids this)."
        )
    if "windowsapps" in low or "pythonsoftwarefoundation.python" in low or "microsoft store" in low:
        hints.append(
            "Your Python is the Microsoft Store build, which has a very long, sandboxed "
            "install path. For heavy ML packages (torch/tensorflow), install Python from "
            "https://www.python.org/downloads/ instead — it avoids long-path and DLL issues."
        )
    if "no space left" in low or "disk full" in low:
        hints.append("The disk appears to be full. Free up space and try again.")
    if hints:
        sys.stdout.write("\n" + "-" * 60 + "\n")
        sys.stdout.write("HINT:\n" + "\n\n".join(hints) + "\n")
        sys.stdout.write("-" * 60 + "\n")




def _aidl_chdir(path: str):
    try:
        os.chdir(path)
        sys.stdout.write(os.getcwd() + "\n")
    except Exception as exc:  # noqa: BLE001
        sys.stdout.write(f"[cd error: {exc}]\n")
    return None


def _transform_line_magics(code: str) -> str:
    """Rewrite ``!shell`` and ``%line-magic`` lines into plain Python calls,
    preserving line count so traceback line numbers stay accurate."""
    out_lines = []
    for line in code.split("\n"):
        m = re.match(r"^(\s*)!pip[0-9.]*\b(.*)$", line)
        if m:
            # Run pip without a shell to avoid Windows path-with-spaces issues.
            indent, args = m.group(1), m.group(2).strip()
            out_lines.append(f"{indent}_aidl_pip({args!r})")
            continue
        m = re.match(r"^(\s*)!(.*)$", line)
        if m:
            indent, cmd = m.group(1), m.group(2).strip()
            out_lines.append(f"{indent}_aidl_shell({cmd!r})")
            continue
        m = re.match(r"^(\s*)%pip\b(.*)$", line)
        if m:
            indent, args = m.group(1), m.group(2).strip()
            out_lines.append(f"{indent}_aidl_pip({args!r})")
            continue
        m = re.match(r"^(\s*)%conda\b(.*)$", line)
        if m:
            indent, args = m.group(1), m.group(2).strip()
            out_lines.append(f"{indent}_aidl_shell({'conda ' + args!r})")
            continue
        m = re.match(r"^(\s*)%cd\s+(.*)$", line)
        if m:
            indent, target = m.group(1), m.group(2).strip().strip("'\"")
            out_lines.append(f"{indent}_aidl_chdir({target!r})")
            continue
        m = re.match(r"^(\s*)%(\w+)\b.*$", line)
        if m and m.group(2) in _NOOP_MAGICS:
            out_lines.append(f"{m.group(1)}pass  # %{m.group(2)} (ignored)")
            continue
        out_lines.append(line)
    return "\n".join(out_lines)


class Kernel:
    def __init__(self, work_dir: str):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.py_ns: Dict[str, object] = {"__name__": "__main__"}
        self._inject_helpers()
        self.aidl_env: Dict[str, object] = {}
        self.exec_count = 0

    def _inject_helpers(self):
        self.py_ns["_aidl_shell"] = _aidl_shell
        self.py_ns["_aidl_pip"] = _aidl_pip
        self.py_ns["_aidl_chdir"] = _aidl_chdir

    # -- public ------------------------------------------------------------
    def reset(self):
        """Restart the runtime (clears all variables)."""
        self.py_ns = {"__name__": "__main__"}
        self._inject_helpers()
        self.aidl_env = {}
        self.exec_count = 0

    def execute(self, code: str, language: str = "python") -> dict:
        self.exec_count += 1
        if language == "aidl":
            return self._execute_aidl(code)
        return self._execute_python(code)

    # -- python ------------------------------------------------------------
    def _execute_python(self, code: str) -> dict:
        # Cell magics (%%bash, %%writefile, %%capture, ...) short-circuit.
        cell_magic = self._maybe_cell_magic(code)
        if cell_magic is not None:
            return cell_magic
        # Rewrite !shell and %line-magic lines into plain Python.
        code = _transform_line_magics(code)

        stdout = io.StringIO()
        stderr = io.StringIO()
        result_text: Optional[str] = None
        images = []
        error = None
        start = time.time()

        prev_cwd = os.getcwd()
        try:
            os.chdir(self.work_dir)
        except Exception:
            pass

        try:
            tree = ast.parse(code, filename="<cell>", mode="exec")
        except SyntaxError as exc:
            os.chdir(prev_cwd)
            return {
                "status": "error",
                "stdout": "",
                "result": None,
                "images": [],
                "error": {
                    "ename": "SyntaxError",
                    "evalue": exc.msg,
                    "line": exc.lineno,
                    "traceback": self._format_syntax_error(exc, code),
                },
                "exec_count": self.exec_count,
            }

        # Split off a trailing expression so we can echo its value (REPL-style).
        last_expr = None
        if tree.body and isinstance(tree.body[-1], ast.Expr):
            last_expr = ast.Expression(tree.body.pop().value)

        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                if tree.body:
                    exec(compile(tree, "<cell>", "exec"), self.py_ns)
                value = None
                if last_expr is not None:
                    value = eval(compile(last_expr, "<cell>", "eval"), self.py_ns)
                images = self._capture_matplotlib()
                if value is not None:
                    result_text = self._repr_value(value)
        except BaseException as exc:  # noqa: BLE001 - we surface everything
            images = self._capture_matplotlib()
            error = self._format_python_exception(exc, code)
        finally:
            os.chdir(prev_cwd)

        combined_out = stdout.getvalue()
        err_stream = stderr.getvalue()
        if err_stream:
            combined_out += err_stream

        return {
            "status": "error" if error else "ok",
            "stdout": combined_out,
            "result": result_text,
            "images": images,
            "error": error,
            "elapsed": round(time.time() - start, 3),
            "exec_count": self.exec_count,
        }

    # -- cell magics -------------------------------------------------------
    def _maybe_cell_magic(self, code: str) -> Optional[dict]:
        start = time.time()
        stripped = code.lstrip("\n")
        if not stripped.startswith("%%"):
            return None
        first, _, rest = stripped.partition("\n")
        first = first.strip()
        prev_cwd = os.getcwd()
        try:
            os.chdir(self.work_dir)
        except Exception:
            pass
        try:
            if first.startswith("%%writefile"):
                parts = shlex.split(first)
                append = "-a" in parts
                fname = parts[-1]
                mode = "a" if append else "w"
                with open(self.work_dir / fname, mode) as fh:
                    fh.write(rest)
                msg = f"{'Appending to' if append else 'Writing'} {fname}"
                return self._ok_result(msg + "\n", start)
            if first in ("%%bash", "%%sh", "%%shell"):
                proc = subprocess.run(rest, shell=True, capture_output=True,
                                      text=True, timeout=1800)
                out = (proc.stdout or "") + (proc.stderr or "")
                return self._ok_result(out, start)
            if first.startswith("%%capture"):
                # Run the body but suppress its output.
                self._execute_python(rest)
                return self._ok_result("", start)
            if first.startswith(("%%time", "%%timeit")):
                return self._execute_python(rest)
            # Unknown cell magic: ignore the directive, run the body.
            return self._execute_python(rest)
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "error", "stdout": "", "result": None, "images": [],
                "error": {"ename": type(exc).__name__, "evalue": str(exc),
                          "line": None, "traceback": traceback.format_exc()},
                "elapsed": round(time.time() - start, 3), "exec_count": self.exec_count,
            }
        finally:
            os.chdir(prev_cwd)

    def _ok_result(self, stdout: str, start: float) -> dict:
        return {
            "status": "ok", "stdout": stdout, "result": None, "images": [],
            "error": None, "elapsed": round(time.time() - start, 3),
            "exec_count": self.exec_count,
        }

    def _make_llm(self):
        """Build an optional LLM callable from server-side env vars (for AIDL
        generate()/agent())."""
        provider = os.getenv("AGENT_LLM_PROVIDER", "").strip().lower()
        if not provider:
            return None
        key = ""
        if provider == "openai":
            key = os.getenv("OPENAI_API_KEY", "")
        elif provider == "gemini":
            key = os.getenv("GOOGLE_API_KEY", "")
        if not key:
            return None
        try:
            import agent
        except Exception:
            return None
        model = os.getenv("AGENT_LLM_MODEL", "")
        return lambda prompt: agent.llm_reply(prompt, provider, key, model)

    # -- aidl --------------------------------------------------------------
    def _execute_aidl(self, code: str) -> dict:
        start = time.time()
        interp = AIDLInterpreter(base_dir=str(self.work_dir), env=self.aidl_env,
                                 llm=self._make_llm())
        try:
            out = interp.run(code)
            return {
                "status": "ok",
                "stdout": out.get("output", ""),
                "result": out.get("result"),
                "images": [],
                "error": None,
                "elapsed": round(time.time() - start, 3),
                "exec_count": self.exec_count,
            }
        except AIDLError as exc:
            partial = interp.out.getvalue() if hasattr(interp, "out") else ""
            return {
                "status": "error",
                "stdout": partial,
                "result": None,
                "images": [],
                "error": {
                    "ename": exc.kind,
                    "evalue": exc.message,
                    "line": exc.line or None,
                    "traceback": f"{exc.kind} (line {exc.line}): {exc.message}"
                    if exc.line else f"{exc.kind}: {exc.message}",
                },
                "exec_count": self.exec_count,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "error",
                "stdout": "",
                "result": None,
                "images": [],
                "error": {
                    "ename": type(exc).__name__,
                    "evalue": str(exc),
                    "line": None,
                    "traceback": traceback.format_exc(),
                },
                "exec_count": self.exec_count,
            }

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _repr_value(value) -> str:
        # Render pandas objects with their nice string form.
        try:
            import pandas as pd
            if isinstance(value, (pd.DataFrame, pd.Series)):
                return value.to_string()
        except Exception:
            pass
        try:
            return repr(value)
        except Exception:
            return str(value)

    @staticmethod
    def _capture_matplotlib():
        images = []
        try:
            import matplotlib.pyplot as plt
        except Exception:
            return images
        try:
            for num in plt.get_fignums():
                fig = plt.figure(num)
                buf = io.BytesIO()
                fig.savefig(buf, format="png", bbox_inches="tight", dpi=110)
                buf.seek(0)
                images.append(base64.b64encode(buf.read()).decode("ascii"))
            plt.close("all")
        except Exception:
            pass
        return images

    @staticmethod
    def _format_syntax_error(exc: SyntaxError, code: str) -> str:
        lines = code.splitlines()
        ctx = ""
        if exc.lineno and 1 <= exc.lineno <= len(lines):
            ctx = f"\n  {lines[exc.lineno - 1]}"
            if exc.offset:
                ctx += "\n  " + " " * (max(exc.offset - 1, 0)) + "^"
        return f"  File \"<cell>\", line {exc.lineno}{ctx}\nSyntaxError: {exc.msg}"

    @staticmethod
    def _format_python_exception(exc: BaseException, code: str) -> dict:
        tb = exc.__traceback__
        # Find the deepest frame that belongs to the user's cell.
        line = None
        node = tb
        while node is not None:
            if node.tb_frame.f_code.co_filename == "<cell>":
                line = node.tb_lineno
            node = node.tb_next
        tb_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        # Hide internal kernel frames for readability.
        tb_text = tb_text.replace(__file__, "<kernel>")
        return {
            "ename": type(exc).__name__,
            "evalue": str(exc),
            "line": line,
            "traceback": tb_text.strip(),
        }


class KernelManager:
    """Keeps one live kernel per notebook id (in-memory, like a Colab runtime)."""

    def __init__(self):
        self._kernels: Dict[str, Kernel] = {}

    def get(self, notebook_id: str, work_dir: str) -> Kernel:
        k = self._kernels.get(notebook_id)
        if k is None:
            k = Kernel(work_dir)
            self._kernels[notebook_id] = k
        return k

    def reset(self, notebook_id: str, work_dir: str) -> Kernel:
        k = Kernel(work_dir)
        self._kernels[notebook_id] = k
        return k

    def drop(self, notebook_id: str):
        self._kernels.pop(notebook_id, None)
