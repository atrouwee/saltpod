#!/bin/bash
# Double-click this from Finder. It starts the local server and opens the page.
# Keep the Terminal window open while you work; close it when you're done.
export DEVELOPER_DIR=/Library/Developer/CommandLineTools
cd "$(dirname "$0")"
exec saltpod
