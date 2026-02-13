@echo off

rem Clean old builds
rmdir /s /q build dist 2>nul

rem Build exe
uvx pyinstaller --name sluggers-stat-editor --noconsole editorV3.py

rem Copy exe and internals into dist\
xcopy /s /y dist\sluggers-stat-editor\* dist\
rmdir /s /q dist\sluggers-stat-editor

rem Copy release-template contents into dist\
xcopy /s /e /y release-template\* dist\

rem Copy source code into dist\Source-Code\
mkdir dist\Source-Code 2>nul
copy /y editorV3.py dist\Source-Code\

echo Build complete: dist\sluggers-stat-editor.exe
