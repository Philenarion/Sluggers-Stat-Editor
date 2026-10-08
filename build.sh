#!/bin/bash
set -e

# Build the executable
uvx pyinstaller --name sluggers-stat-editor --onefile --noconsole editor.py

# Copy release-template contents into dist/
cp -r release-template/* dist/

# Copy source code into dist/Source-Code/
mkdir -p dist/Source-Code dist/Bridge
cp editor.py sluggies_bridge.py dist/Source-Code/

echo "Build complete: dist/sluggers-stat-editor"
