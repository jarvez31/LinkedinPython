#!/bin/bash

# LinkedinPython — One-line setup script
# Usage: bash setup.sh

set -e

echo ""
echo "╔═══════════════════════════════════════╗"
echo "║     LinkedinPython Setup               ║"
echo "║     Job Intelligence Dashboard        ║"
echo "╚═══════════════════════════════════════╝"
echo ""

# ── Check Python ──────────────────────────────────────────────────────────────
echo "▶ Checking Python..."
if ! command -v python3 &> /dev/null; then
    echo "✗ Python 3 not found. Install it from https://python.org and re-run."
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  ✓ Python $PYTHON_VERSION found"

# ── Create virtual environment ────────────────────────────────────────────────
echo ""
echo "▶ Creating virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "  ✓ Virtual environment created"
else
    echo "  ✓ Virtual environment already exists"
fi

# Activate
source venv/bin/activate

# ── Install dependencies ───────────────────────────────────────────────────────
echo ""
echo "▶ Installing dependencies..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo "  ✓ Dependencies installed"

# ── Install Playwright + Chromium ─────────────────────────────────────────────
echo ""
echo "▶ Installing Playwright + Chromium browser..."
echo "  (This may take 1-2 minutes on first run)"
playwright install chromium
echo "  ✓ Chromium installed"

# ── Create folder structure ───────────────────────────────────────────────────
echo ""
echo "▶ Creating folders..."
mkdir -p data outputs attachments
echo "  ✓ data/, outputs/, attachments/ ready"

# ── .env setup ────────────────────────────────────────────────────────────────
echo ""
echo "▶ Checking .env..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "  ✓ .env created from .env.example"
    echo "  ⚠ Edit .env and add your ANTHROPIC_API_KEY before running"
else
    echo "  ✓ .env already exists"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "╔═══════════════════════════════════════╗"
echo "║  Setup complete!                      ║"
echo "╚═══════════════════════════════════════╝"
echo ""
echo "To start the dashboard:"
echo ""
echo "  source venv/bin/activate"
echo "  python app.py"
echo ""
echo "Then open http://localhost:5000 in your browser."
echo ""
echo "Note: LinkedIn credentials and Anthropic API key"
echo "are entered in the dashboard UI — not stored anywhere."
echo ""
