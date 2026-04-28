#!/bin/bash
# ============================================================
# GET ME A JOB — Setup Script for Linux KDE Neon
# Run this once: bash setup.sh
# ============================================================
set -e

echo ""
echo "╔══════════════════════════════════════╗"
echo "║      GET ME A JOB — Setup            ║"
echo "╚══════════════════════════════════════╝"
echo ""

# --- System dependencies (WeasyPrint needs these) ---
echo "[1/5] Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
  python3-pip python3-venv python3-dev \
  libpango-1.0-0 libpangocairo-1.0-0 \
  libcairo2 libcairo2-dev \
  libgdk-pixbuf2.0-0 \
  libffi-dev \
  shared-mime-info \
  fonts-liberation fonts-dejavu \
  libxml2-dev libxslt1-dev \
  build-essential \
  chromium-browser 2>/dev/null || \
  sudo apt-get install -y -qq chromium 2>/dev/null || true

echo "✓ System dependencies installed"

# --- Python virtual environment ---
echo ""
echo "[2/5] Creating Python virtual environment..."
if [ ! -d "venv" ]; then
  python3 -m venv venv
  echo "✓ venv created"
else
  echo "✓ venv already exists"
fi

source venv/bin/activate

# --- Python packages ---
echo ""
echo "[3/5] Installing Python packages..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "✓ Python packages installed"

# --- Playwright browsers ---
echo ""
echo "[4/5] Installing Playwright browsers (Chromium)..."
playwright install chromium
playwright install-deps chromium
echo "✓ Playwright Chromium installed"

# --- Create required directories ---
echo ""
echo "[5/5] Creating project directories..."
mkdir -p resumes/generated output data
echo "✓ Directories created"

# --- Done ---
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║                  SETUP COMPLETE                      ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Next steps:                                         ║"
echo "║                                                      ║"
echo "║  1. Start LM Studio → load any model (7B+ works)    ║"
echo "║  2. Drop your resume at: resumes/my_resume.pdf       ║"
echo "║  3. Edit config.yaml:                                ║"
echo "║     - Add your LinkedIn li_at cookie                 ║"
echo "║     - Set your expected salary range                 ║"
echo "║     - Set your location & contact info               ║"
echo "║  4. Test everything:                                 ║"
echo "║       source venv/bin/activate                       ║"
echo "║       python main.py check                           ║"
echo "║  5. Run the agent:                                   ║"
echo "║       python main.py run                             ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
