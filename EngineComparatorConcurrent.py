import subprocess
import os
import sys
import concurrent.futures
import multiprocessing
import argparse
import shutil
import threading
import signal
import time
import math

# Global flags for clean shutdown
print_lock = threading.Lock()
stop_event = threading.Event()

# --- 1. ARGUMENT PARSING ---
def parse_arguments():
    parser = argparse.ArgumentParser(description="Incremental Multi-Engine Tournament (Real-Time Output)")

    # Paths
    parser.add_argument("--cutechess", required=True, help="Path to cutechess-cli.exe")
    parser.add_argument("--engines", nargs='+', required=True, help="List of paths to engine executables")
    parser.add_argument("--openings", required=True, help="Folder containing opening files OR a single .csv/.epd file")
    parser.add_argument("--results", required=True, help="Folder to save PGN results")

    # Settings
    parser.add_argument("--rounds", type=int, default=1, help="Number of Round-Robin cycles")
    parser.add_argument("--games_per_round", type=int, default=2, help="Games per pairing in each round")
    parser.add_argument("--time", type=float, default=60.0, help="Seconds per move")
    parser.add_argument("--margin", type=int, default=1000, help="Time margin in ms")
    
    # Resources
    parser.add_argument("--concurrency", type=int, default=1, help="Number of parallel tournaments")
    parser.add_argument("--total_memory", type=int, required=True, help="TOTAL Memory (MB) to allocate system-wide")

    return parser.parse_args()

# --- 2. HELPER FUNCTIONS ---

def count_games_in_pgn(pgn_path):
    if not os.path.exists(pgn_path):
        return 0
    count = 0
    try:
        with open(pgn_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                if line.startswith("[Result"):
                    count += 1
    except Exception:
        return 0
    return count

def get_engine_name(engine_path):
    return os.path.splitext(os.path.basename(engine_path))[0]

# --- 3. WORKER FUNCTION ---

def run_tournament_task(args, openings_folder, filename, calculated_hash):
    # Check if stop was requested before starting
    if stop_event.is_set():
        return

    openings_file_path = os.path.join(openings_folder, filename)
    
    # Identify output name. If using temp chunks, map "chunk_X.epd" -> "results_chunk_X.pgn"
    # This maintains resume capability if the user restarts with the same CSV.
    result_filename = f"results_{filename}.pgn"
    if result_filename.endswith(".epd.pgn"):
        result_filename = result_filename.replace(".epd.pgn", ".pgn")
        
    final_output_path = os.path.join(args.results, result_filename)
    
    # --- MATH ---
    num_engines = len(args.engines)
    pairings = num_engines * (num_engines - 1) // 2
    games_per_cycle = pairings * args.games_per_round
    total_games_target = args.rounds * games_per_cycle
    
    games_already_played = count_games_in_pgn(final_output_path)

    # --- SMART OVERWRITE LOGIC ---
    if 0 < games_already_played < games_per_cycle:
        with print_lock:
            print(f"[RESET] {filename}: Found {games_already_played} games (incomplete round). Deleting and restarting.")
        try:
            os.remove(final_output_path)
            games_already_played = 0
        except OSError:
            pass

    games_remaining = total_games_target - games_already_played
    
    if games_remaining <= 0:
        with print_lock:
            print(f"[SKIP] {filename} complete.")
        return

    rounds_needed = (games_remaining + games_per_cycle - 1) // games_per_cycle
    
    with print_lock:
        print(f" -> Starting {filename} ({rounds_needed} rounds needed)")

    # --- COMMAND SETUP ---
    temp_output_path = os.path.join(args.results, f"temp_{filename}.pgn")
    
    cmd = [
        args.cutechess,
        "-tournament", "round-robin",
    ]

    for engine_path in args.engines:
        e_name = get_engine_name(engine_path)
        cmd.extend([
            "-engine", 
            f"name={e_name}", 
            f"cmd={engine_path}",
            f"option.Threads=1",
            f"option.Hash={calculated_hash}"
        ])

    cmd.extend([
        "-openings", f"file={openings_file_path}", "format=epd", "order=random",
        "-each", "proto=uci", f"st={args.time}", f"timemargin={args.margin}",
        "-rounds", str(rounds_needed),
        "-games", str(args.games_per_round),
        "-repeat",
        "-pgnout", temp_output_path
    ])

    process = None
    try:
        # Start Cutechess
        process = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT, 
            text=True, 
            bufsize=1, 
            universal_newlines=True
        )

        # Read output line-by-line
        while True:
            # If Ctrl+C happened, kill the process
            if stop_event.is_set():
                process.terminate()
                process.wait()
                if os.path.exists(temp_output_path):
                    os.remove(temp_output_path)
                return

            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            
            if line:
                line = line.strip()
                if "Finished game" in line:
                    with print_lock:
                        print(f"[{filename}] {line}")

        if process.returncode != 0 and not stop_event.is_set():
            with print_lock:
                print(f"[ERROR] {filename} failed (Code: {process.returncode})")
            if os.path.exists(temp_output_path):
                os.remove(temp_output_path)
            return

        # --- MERGE RESULTS ---
        if os.path.exists(temp_output_path) and not stop_event.is_set():
            mode = "a" if os.path.exists(final_output_path) else "w"
            with open(final_output_path, mode) as main_file:
                with open(temp_output_path, "r") as temp_file:
                    if mode == "a": main_file.write("\n")
                    shutil.copyfileobj(temp_file, main_file)
            os.remove(temp_output_path)
            
        with print_lock:
            if not stop_event.is_set():
                print(f" [DONE] Finished: {filename}")

    except Exception as e:
        with print_lock:
            print(f"[CRITICAL ERROR] {filename}: {e}")
        if process:
            process.kill()
        if os.path.exists(temp_output_path):
            os.remove(temp_output_path)

# --- 4. MAIN EXECUTION ---

if __name__ == "__main__":
    args = parse_arguments()
    
    # Setup Signals for Ctrl+C
    def signal_handler(sig, frame):
        print("\n\n[STOPPING] Ctrl+C detected. Shutting down engines. Please wait...")
        stop_event.set()
        
    signal.signal(signal.SIGINT, signal_handler)

    os.makedirs(args.results, exist_ok=True)

    # --- LOGIC TO HANDLE CSV INPUT vs FOLDER INPUT ---
    active_openings_dir = args.openings
    files = []

    if os.path.isfile(args.openings):
        print(f"[INFO] Detected single input file: {args.openings}")
        print("[INFO] Parsing and splitting into chunks...")
        
        # Read FENs from CSV (Output.csv format: FEN,Hit,WDL,ChessEngine)
        fens = []
        try:
            with open(args.openings, 'r', encoding='utf-8-sig') as f:
                lines = [l.strip() for l in f if l.strip()]
                start_idx = 0
                # Basic header detection
                if "FEN" in lines[0] and "," in lines[0]:
                    start_idx = 1
                
                for line in lines[start_idx:]:
                    # Extract FEN (everything before first comma)
                    if "," in line:
                        fen_part = line.split(",", 1)[0].strip()
                    else:
                        fen_part = line.strip()
                    if fen_part:
                        fens.append(fen_part)
        except Exception as e:
            sys.exit(f"[ERROR] Reading file failed: {e}")

        if not fens:
            sys.exit("[ERROR] No FENs found in the input file.")

        print(f"[INFO] Loaded {len(fens)} positions.")

        # Create a temp folder inside results to store the split EPDs
        temp_dir = os.path.join(args.results, "_temp_chunks")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        os.makedirs(temp_dir)
        active_openings_dir = temp_dir

        # Split into chunks based on concurrency
        # Use ceil to ensure we don't drop the last items
        chunk_size = math.ceil(len(fens) / args.concurrency)
        
        for i in range(args.concurrency):
            start = i * chunk_size
            end = start + chunk_size
            chunk = fens[start:end]
            
            if not chunk:
                break
                
            chunk_filename = f"chunk_{i+1:02d}.epd"
            chunk_path = os.path.join(temp_dir, chunk_filename)
            with open(chunk_path, 'w') as cf:
                cf.write("\n".join(chunk))
            
            files.append(chunk_filename)
            
        print(f"[INFO] Created {len(files)} chunks in {temp_dir}")

    elif os.path.isdir(args.openings):
        active_openings_dir = args.openings
        files = [f for f in os.listdir(args.openings) if os.path.isfile(os.path.join(args.openings, f))]
        if not files:
            sys.exit("No opening files found in the folder.")
    else:
        sys.exit(f"Error: {args.openings} is not a valid file or directory.")

    # Memory Calculation
    active_threads = args.concurrency * 2
    calculated_hash = args.total_memory // active_threads
    calculated_hash = max(1, calculated_hash)

    print(f"--- Real-Time Engine Comparator ---")
    print(f" Concurrency:    {args.concurrency}")
    print(f" Memory:         {calculated_hash} MB per engine")
    print("-" * 50)

    # Use ThreadPoolExecutor
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency)
    futures = []

    try:
        # Submit all tasks
        for f in files:
            if stop_event.is_set(): break
            # Pass active_openings_dir explicitly
            futures.append(executor.submit(run_tournament_task, args, active_openings_dir, f, calculated_hash))
        
        # Monitor Loop
        while not stop_event.is_set():
            # Check if all futures are done
            if all(f.done() for f in futures):
                break
            time.sleep(0.5)

    except KeyboardInterrupt:
        stop_event.set()
    
    finally:
        # Shutdown logic
        if stop_event.is_set():
            print("[CLEANUP] Killing active games...")
            
        # This will cancel pending futures and wait for running ones to finish (which we kill via stop_event)
        executor.shutdown(wait=True, cancel_futures=True)
        print("--- Stopped. ---")