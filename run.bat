@echo off
cd /d A:\ml
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
