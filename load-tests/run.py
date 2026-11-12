import os
import sys
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent
SCENARIOS_DIR = BASE_DIR / "scenarios"
RESULTS_DIR = BASE_DIR / "results"

TESTS = {
    "1": {
        "name": "Smoke Test",
        "file": "smoke.js",
        "description": "Basic functionality check"
    },
    "2": {
        "name": "Load Test",
        "file": "load.js",
        "description": "Expected traffic simulation"
    },
    "3": {
        "name": "Stress Test",
        "file": "stress.js",
        "description": "Find system limits"
    },
    "4": {
        "name": "Spike Test",
        "file": "spike.js",
        "description": "Sudden traffic increase"
    },
    "5": {
        "name": "Soak Test",
        "file": "soak.js",
        "description": "Long-duration stability"
    },
    "6": {
        "name": "Custom Test",
        "file": "load.js",
        "description": "Custom VUs and duration"
    },
}


def ask_number(prompt, default, minimum=1):
    while True:
        value = input(f"{prompt} [{default}]: ").strip()

        if not value:
            return default

        try:
            number = int(value)
            if number >= minimum:
                return number
        except ValueError:
            pass

        print(f"Please enter a number >= {minimum}.")


def ask_duration(prompt, default):
    value = input(f"{prompt} [{default}]: ").strip() or default

    if not value.endswith(("s", "m", "h")):
        print("Use duration like 30s, 2m, or 1h.")
        return ask_duration(prompt, default)

    try:
        if int(value[:-1]) <= 0:
            raise ValueError
    except ValueError:
        print("Invalid duration.")
        return ask_duration(prompt, default)

    return value


def main():
    print("\n========================================")
    print("   DEEPRESEARCH AI - PERFORMANCE LAB")
    print("========================================")

    if not os.getenv("ACCESS_TOKEN"):
        print("\n⚠️ ACCESS_TOKEN is not set.")
        print("Run: export ACCESS_TOKEN='your_token'")
        return

    print("\nSelect a test type:\n")

    for key, test in TESTS.items():
        print(f"{key}. {test['name']} - {test['description']}")

    choice = input("\nChoose an option (1-6): ").strip()

    if choice not in TESTS:
        print("Invalid option.")
        return

    test = TESTS[choice]

    defaults = {
        "1": (1, "1m"),
        "2": (25, "2m"),
        "3": (100, "5m"),
        "4": (100, "2m"),
        "5": (10, "30m"),
        "6": (10, "1m"),
    }

    default_vus, default_duration = defaults[choice]

    vus = ask_number("Virtual Users", default_vus)
    duration = ask_duration("Duration", default_duration)

    ramp_up = 0
    ramp_down = 0

    if choice in ("2", "3", "4", "5", "6"):
        ramp_up = ask_number("Ramp-up seconds", 30, 0)
        ramp_down = ask_number("Ramp-down seconds", 15, 0)

    think_time = ask_number("Think time (seconds)", 1, 0)

    print("\n========== TEST CONFIGURATION ==========")
    print(f"Test       : {test['name']}")
    print(f"Virtual Users: {vus}")
    print(f"Duration   : {duration}")
    print(f"Ramp-up    : {ramp_up}s")
    print(f"Ramp-down  : {ramp_down}s")
    print(f"Think time : {think_time}s")

    confirm = input("\nStart test? (y/n): ").strip().lower()

    if confirm != "y":
        print("Test cancelled.")
        return

    scenario = SCENARIOS_DIR / test["file"]

    if not scenario.exists():
        print(f"Scenario not found: {scenario}")
        return

    RESULTS_DIR.mkdir(exist_ok=True)

    base_url = os.getenv("BASE_URL", "http://localhost:8000")
    report = RESULTS_DIR / f"{test['file'].replace('.js', '')}-latest.json"

    cmd = [
        "k6", "run",
        "-e", f"VUS={vus}",
        "-e", f"DURATION={duration}",
        "-e", f"RAMP_UP={ramp_up}",
        "-e", f"RAMP_DOWN={ramp_down}",
        "-e", f"THINK_TIME={think_time}",
        "-e", f"BASE_URL={base_url}",
        "--summary-export", str(report),
        str(scenario),
    ]

    print("\n🚀 Starting k6...\n")

    try:
        subprocess.run(cmd, check=False)
        print(f"\n📊 Report saved at: {report}")
    except FileNotFoundError:
        print("k6 is not installed or not available in PATH.")


if __name__ == "__main__":
    main()
