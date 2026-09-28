#!/bin/bash
# Double-click this from Finder. It starts the local server and opens the page.
# Keep the Terminal window open while you work; close it when you're done.
# Only a fallback. An unaccepted Xcode licence makes /usr/bin/git and
# friends refuse to run; pointing at the Command Line Tools sidesteps it
# without asking anyone for sudo. A machine with the licence accepted --
# or a deliberate DEVELOPER_DIR -- keeps its own.
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}"
cd "$(dirname "$0")"
exec saltpod
