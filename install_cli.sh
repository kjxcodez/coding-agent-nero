#!/bin/bash
set -e

echo "=========================================="
echo "  NERO CLI Local Installation Helper"
echo "=========================================="
echo ""

# Check if inside virtual environment
if [ -z "$VIRTUAL_ENV" ]; then
    echo "[WARNING] No active virtual environment detected."
    echo "It is highly recommended to activate your virtual env (e.g., source .venv/bin/activate) first."
    read -p "Do you want to proceed installing globally? [y/N]: " choice
    if [[ ! "$choice" =~ ^[Yy]$ ]]; then
        echo "Installation cancelled."
        exit 0
    fi
fi

echo "Installing NERO in editable mode..."
pip install -e .

echo ""
echo "=========================================="
echo "  [SUCCESS] NERO CLI Installed!"
echo "=========================================="
echo ""
echo "You can now run NERO anywhere by typing:"
echo "  nero"
echo ""
