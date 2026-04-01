#!/bin/bash
# OMEGA Memory -- macOS uninstall script
# Removes OMEGA installation while preserving user data (~/.omega).

set -euo pipefail

INSTALL_DIR="$HOME/Library/OMEGA"
PYTHON="$INSTALL_DIR/python/bin/python3"
CONFIGURE="$INSTALL_DIR/configure_claude.py"
PKG_ID="com.omega.memory"

echo "OMEGA Uninstaller"
echo "================="
echo ""

# Step 1: Remove OMEGA from Claude Desktop config
echo "Removing OMEGA from Claude Desktop configuration..."
if [ -f "$CONFIGURE" ] && [ -f "$PYTHON" ]; then
    "$PYTHON" "$CONFIGURE" --uninstall 2>/dev/null || echo "  (config already clean)"
else
    echo "  Skipped (installer files not found)"
fi

# Step 2: Remove install directory
echo "Removing OMEGA installation directory..."
if [ -d "$INSTALL_DIR" ]; then
    rm -rf "$INSTALL_DIR"
    echo "  Removed $INSTALL_DIR"
else
    echo "  Already removed"
fi

# Step 3: Forget package receipt
echo "Removing package receipt..."
pkgutil --pkg-info "$PKG_ID" &>/dev/null && pkgutil --forget "$PKG_ID" 2>/dev/null || echo "  No receipt found"

# Step 4: Preserve user data
echo ""
echo "Your OMEGA memory data has been preserved at: ~/.omega"
echo "To remove it permanently: rm -rf ~/.omega"
echo ""
echo "OMEGA has been uninstalled. Restart Claude Desktop."
