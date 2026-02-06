# Incremental Multi-Engine Tournament Runner

This Python script runs automated Round-Robin chess tournaments in parallel using `cutechess-cli`. It is designed for reliability, allowing you to stop and restart tournaments without losing data or creating unbalanced results.

## Key Features

* **Parallel Execution:** Runs multiple tournament threads simultaneously (1 thread per opening file).
* **Incremental Resume:**
    * **Finished Files:** Automatically skipped.
    * **Partial/Broken Files:** If a file has an incomplete round (e.g., 3 out of 6 games), the script **deletes and restarts** that specific file to ensure fair pairings.
    * **New Files:** Started from game 1.
* **Real-Time Output:** Prints game results (e.g., `1-0`, `1/2-1/2`) and engine names to the console as they finish.
* **Memory Management:** Automatically calculates the safe Hash (MB) per engine based on your defined `--total_memory` limit.
* **Safe Shutdown:** Handles `Ctrl+C` gracefully by killing active engine processes and cleaning up temporary files.

## Prerequisites

1.  **Python 3.x** installed.
2.  **Cutechess-CLI:** The command-line tournament manager.
3.  **Chess Engines:** At least 3 UCI engines (e.g., Stockfish, Reckless, ShashChess).
4.  **Openings:** A folder containing `.epd` or `.fen` files (recommended: 1 position per file).

## Usage

Run the script from the command line (CMD or PowerShell).

### Required Arguments

| Argument | Description |
| :--- | :--- |
| `--cutechess` | Full path to `cutechess-cli.exe`. |
| `--engines` | List of full paths to engine executables (space-separated). |
| `--openings` | Folder containing your FEN/EPD files. |
| `--results` | Folder where PGN results will be saved. |
| `--total_memory` | Total RAM (in MB) to allocate for the *entire* script. |
| `--concurrency` | Number of tournaments (files) to run in parallel. |

### Optional Arguments

| Argument | Default | Description |
| :--- | :--- | :--- |
| `--rounds` | `1` | Number of full Round-Robin cycles. |
| `--games_per_round`| `2` | Games per pairing (White/Black). |
| `--time` | `60.0` | Thinking time per move (seconds). |
| `--margin` | `1000` | Time margin in milliseconds. |

### Example Command

**PowerShell:**

```powershell
python EngineComparator.py `
  --cutechess "C:\Chess\cutechess-cli.exe" `
  --engines "C:\Chess\stockfish.exe" "C:\Chess\reckless.exe" "C:\Chess\shash.exe" `
  --openings "C:\Chess\Openings" `
  --results "C:\Chess\Results" `
  --total_memory 4096 `
  --concurrency 4 `
  --time 60.0 `
  --rounds 1