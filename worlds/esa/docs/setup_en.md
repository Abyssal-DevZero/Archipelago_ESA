# Environmental Station Alpha Setup Guide

## Required Software

- Environmental Station Alpha
- The Archipelago Launcher, version 0.6.7 or newer
- The Environmental Station Alpha `.apworld`

The client reads and writes the running game's memory, so it is **Windows only**
and needs 64-bit Python. Running under Proton or Wine may work if the Launcher
runs inside the same prefix as the game, but this is untested.

## Installation

1. Download `environmental_station_alpha.apworld`.
2. Open the Archipelago Launcher and press Install APWorld, then pick the
   file. (Or drop it into the worlds folder by hand.)

## Generating a game

Press **Generate Template Options** in the Launcher, or use the Options Creator, to produce a starting YAML. Fill it in and generate as normal.

## Before you play

Start a **new save file**. An existing save already has pickup flags set; the client will read those as checks and send them the moment you connect.

## Playing

1.  Open the Archipelago Launcher and start Environmental Station Alpha Client.
2.  Launch Environmental Station Alpha and start a new game.
3.  Enter the server address and your slot name when prompted.

The client patches the running game in memory each session, nothing is written to the executable, and nothing needs undoing afterwards. If you close the game, the client will re-attach and re-patch when you start it again.

## Client commands

| Command | Effect |
|---|---|
| `/esa` | Attach state, patch state and inventory summary |
| `/goal` | Mark the seed finished (manual — the final boss flag is unmapped) |
| `/patch` | Force a re-patch on the next poll |
| `/unpatch` | Restore the game |

- Goal completion is manual: type `/goal` after finishing
