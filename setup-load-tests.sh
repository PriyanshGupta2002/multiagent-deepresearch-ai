
#!/bin/bash

set -e

echo "🚀 Setting up DeepResearch AI Performance Testing..."

BASE_DIR="load-tests"

# Create folder structure
mkdir -p "$BASE_DIR"/{scenarios,results}

# Create Python CLI entry point
cat > "$BASE_DIR/run.py" <<'PYTHON'
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
PYTHON

# Create shared k6 scenario files
create_scenario() {
    local filename="$1"
    local executor="$2"

    cat > "$BASE_DIR/scenarios/$filename" <<EOF
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const ACCESS_TOKEN = __ENV.ACCESS_TOKEN;

const VUS = Number(__ENV.VUS || 10);
const DURATION = __ENV.DURATION || '1m';
const RAMP_UP = Number(__ENV.RAMP_UP || 30);
const RAMP_DOWN = Number(__ENV.RAMP_DOWN || 15);
const THINK_TIME = Number(__ENV.THINK_TIME || 1);

export const options = {
  scenarios: {
    research_list: {
      executor: '$executor',
EOF

    if [ "$executor" = "ramping-vus" ]; then
        cat >> "$BASE_DIR/scenarios/$filename" <<'EOF'
      startVUs: 0,
      stages: [
        { duration: `${RAMP_UP}s`, target: VUS },
        { duration: DURATION, target: VUS },
        { duration: `${RAMP_DOWN}s`, target: 0 },
      ],
EOF
    elif [ "$executor" = "constant-arrival-rate" ]; then
        cat >> "$BASE_DIR/scenarios/$filename" <<'EOF'
      rate: VUS,
      timeUnit: '1s',
      duration: DURATION,
      preAllocatedVUs: VUS,
      maxVUs: VUS * 2,
EOF
    else
        cat >> "$BASE_DIR/scenarios/$filename" <<'EOF'
      vus: VUS,
      duration: DURATION,
EOF
    fi

    cat >> "$BASE_DIR/scenarios/$filename" <<'EOF'
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<1000'],
  },
};

export default function () {
  const response = http.get(
    `${BASE_URL}/api/v1/research?page=1&limit=20`,
    {
      headers: {
        Cookie: `access_token=${ACCESS_TOKEN}`,
        Accept: 'application/json',
      },
      tags: { endpoint: 'research_list' },
    }
  );

  check(response, {
    'status is 200': (r) => r.status === 200,
    'response is not empty': (r) => r.body && r.body.length > 0,
  });

  if (THINK_TIME > 0) {
    sleep(THINK_TIME);
  }
}
EOF
}

# Generate scenarios
create_scenario "smoke.js" "constant-vus"
create_scenario "load.js" "ramping-vus"
create_scenario "stress.js" "ramping-vus"
create_scenario "spike.js" "constant-arrival-rate"
create_scenario "soak.js" "constant-vus"

# Create README
cat > "$BASE_DIR/README.md" <<'EOF'
# DeepResearch AI - Performance Testing

## Requirements

- Python 3
- k6
- Valid ACCESS_TOKEN

## Run

```bash
export ACCESS_TOKEN='your-token'
python load-tests/run.py
```

## Test Scenarios

- Smoke Test
- Load Test
- Stress Test
- Spike Test
- Soak Test
- Custom Test

Reports are stored in `results/`.
EOF

echo ""
echo "✅ Performance testing structure created!"
echo ""
find "$BASE_DIR" -maxdepth 2 -type f
echo ""
echo "Next:"
echo "1. export ACCESS_TOKEN='your-token'"
echo "2. python load-tests/run.py"
