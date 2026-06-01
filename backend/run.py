import uvicorn
import sys
import os

# Ensure repository root is on sys.path so "backend.xxx" imports resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Force UTF-8 encoding on Windows to prevent charmap codec errors
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

if __name__ == "__main__":
    uvicorn.run("backend.api.main:app", host="0.0.0.0", port=8081, reload=True)
