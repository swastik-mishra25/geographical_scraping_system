"""Application runner for Dakini Geographical Lead Discovery & Qualification POC.

Usage:
    .venv\\Scripts\\python run.py                     (Starts on 127.0.0.1:8000 with auto-reload)
    .venv\\Scripts\\python run.py --port 8001         (Starts on port 8001)
    .venv\\Scripts\\python run.py --kill              (Kills existing process on port 8000 and starts)
    .venv\\Scripts\\python run.py --no-reload         (Starts without reload for production stability)
"""
import os
import re
import socket
import subprocess
import sys
import warnings

# Suppress known Pydantic V1 compat UserWarning on Python 3.14+
warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    module=r"fastapi\._compat\.v1",
)
warnings.filterwarnings(
    "ignore",
    message=r".*Core Pydantic V1 functionality isn't compatible.*",
)


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Test if a local TCP port is already open or bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex((host, port)) == 0


def kill_process_on_port(port: int) -> bool:
    """Find and kill process holding specified port on Windows."""
    try:
        output = subprocess.check_output(f'netstat -ano | findstr ":{port} "', shell=True, text=True)
        pids = set()
        for line in output.strip().splitlines():
            parts = line.strip().split()
            if len(parts) >= 5 and "LISTENING" in line:
                pid = parts[-1]
                if pid.isdigit() and int(pid) != os.getpid():
                    pids.add(pid)
        for pid in pids:
            print(f"[server] Terminating previous process PID {pid} on port {port}...")
            subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
        return bool(pids)
    except Exception:
        return False


if __name__ == "__main__":
    import uvicorn

    args = sys.argv[1:]

    # Parse --port argument
    port = int(os.getenv("PORT", "8000"))
    for idx, arg in enumerate(args):
        if arg == "--port" and idx + 1 < len(args) and args[idx + 1].isdigit():
            port = int(args[idx + 1])
        elif arg.startswith("--port="):
            val = arg.split("=", 1)[1]
            if val.isdigit():
                port = int(val)

    # Parse --host argument
    host = os.getenv("HOST", "127.0.0.1")
    for idx, arg in enumerate(args):
        if arg == "--host" and idx + 1 < len(args):
            host = args[idx + 1]
        elif arg.startswith("--host="):
            host = arg.split("=", 1)[1]

    reload = "--no-reload" not in args
    should_kill = "--kill" in args or "--force" in args

    # Check port availability
    if is_port_in_use(port, host):
        if should_kill:
            kill_process_on_port(port)
            import time
            time.sleep(0.5)
        else:
            print(f"\n=======================================================")
            print(f" WARNING: Port {port} is ALREADY IN USE by another process.")
            print(f"=======================================================")
            print(f" Options to resolve:")
            print(f"   1. Use existing running instance at: http://{host}:{port}")
            print(f"   2. Start on another port:   .venv\\Scripts\\python run.py --port {port + 1}")
            print(f"   3. Kill existing process:   .venv\\Scripts\\python run.py --kill")
            print(f"=======================================================\n")
            sys.exit(1)

    print(f"\n=======================================================")
    print(f" Dakini AI - Geographical Lead Discovery & Qualification")
    print(f" URL: http://{host}:{port}")
    print(f" Mode: {'Auto-reload on app/ changes' if reload else 'Production (No reload)'}")
    print(f"=======================================================\n")

    try:
        if reload:
            uvicorn.run(
                "app.main:app",
                host=host,
                port=port,
                reload=True,
                reload_dirs=["app"],
                log_level="info",
            )
        else:
            uvicorn.run(
                "app.main:app",
                host=host,
                port=port,
                reload=False,
                log_level="info",
            )
    except KeyboardInterrupt:
        print("\n[server] Server stopped cleanly.")
    except Exception as exc:
        print(f"\n[server] Error starting server on {host}:{port}: {exc}")
        print(f"[server] If port is restricted, try running: .venv\\Scripts\\python run.py --port {port + 1}\n")
        sys.exit(1)
