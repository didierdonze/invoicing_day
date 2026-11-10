# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

New project — no code yet. Add build/test commands and architecture notes here as they appear.

## Working locally and on claude.ai/code

This repository is used both from the local CLI and from Claude Code on the web (cloud sessions clone it from GitHub `didierdonze/invoicing_day`). Cloud sessions only see what is committed: anything a session needs (skills, agents, commands, MCP config, project settings) must live in the repo under `.claude/` or `.mcp.json`, not in `~/.claude/`. Secrets go in the cloud environment's variables, never in the repo.
