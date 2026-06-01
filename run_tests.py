#!/usr/bin/env python
"""
SQL to DynamoDB Design Mentor Test Runner — Consolidated script to run all test tiers.

Usage:
    python run_tests.py                    # Run fast tests only (no Bedrock)
    python run_tests.py --tier 1           # Roslyn tests only
    python run_tests.py --tier 2           # Extraction tests (requires Bedrock)
    python run_tests.py --tier 3           # Full pipeline E2E (requires Bedrock)
    python run_tests.py --tier 4           # Drift detection (uses DB history)
    python run_tests.py --all              # Run all tiers
    python run_tests.py --profile myprof   # Use specific AWS profile

Environment:
    AWS_PROFILE: AWS profile with Bedrock access (default: "default")
"""

import argparse
import os
import sys
import subprocess


def main():
    parser = argparse.ArgumentParser(description="SQL to DynamoDB Design Mentor Test Runner")
    parser.add_argument("--tier", type=int, choices=[0, 1, 2, 3, 4],
                        help="Run specific test tier (0=infra, 1=roslyn, 2=extraction, 3=e2e, 4=drift)")
    parser.add_argument("--all", action="store_true", help="Run all test tiers")
    parser.add_argument("--fast", action="store_true", help="Run only fast tests (tier 0+1, no Bedrock)")
    parser.add_argument("--profile", type=str, help="AWS profile name for Bedrock access")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    # Set AWS profile
    if args.profile:
        os.environ["AWS_PROFILE"] = args.profile

    # Determine which tiers to run
    if args.all:
        tiers = [0, 1, 2, 3, 4]
    elif args.fast:
        tiers = [0, 1]
    elif args.tier is not None:
        tiers = [args.tier]
    else:
        tiers = [0, 1]  # Default: fast tests

    tier_map = {
        0: ("Infrastructure", "backend/tests/test_infrastructure.py"),
        1: ("Roslyn Deterministic", "backend/tests/test_roslyn.py"),
        2: ("Extraction (Bedrock)", "backend/tests/test_extraction.py"),
        3: ("Pipeline E2E (Bedrock)", "backend/tests/test_pipeline_e2e.py"),
        4: ("Cross-Run Drift (DB History)", "backend/tests/test_consistency.py"),
    }

    project_root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_root)

    # Ensure project root is on PYTHONPATH
    env = os.environ.copy()
    env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")

    results = {}
    total_passed = 0
    total_failed = 0

    for tier in tiers:
        name, test_file = tier_map[tier]
        print(f"\n{'='*60}")
        print(f"  Tier {tier}: {name}")
        print(f"  File: {test_file}")
        print(f"{'='*60}\n")

        cmd = [sys.executable, "-m", "pytest", test_file, "-x"]
        if args.verbose:
            cmd.append("-v")
        else:
            cmd.append("-q")

        # Add markers for Bedrock tests
        if tier >= 2:
            profile = os.environ.get("AWS_PROFILE", "default")
            print(f"  AWS Profile: {profile}")

        result = subprocess.run(cmd, cwd=project_root, env=env)
        passed = result.returncode == 0
        results[tier] = {"name": name, "passed": passed, "returncode": result.returncode}

        if passed:
            total_passed += 1
        else:
            total_failed += 1

        # Stop on failure unless running all
        if not passed and not args.all:
            print(f"\n❌ Tier {tier} ({name}) FAILED — stopping.")
            break

    # Summary
    print(f"\n{'='*60}")
    print(f"  TEST SUMMARY")
    print(f"{'='*60}")
    for tier, info in results.items():
        status = "✅ PASSED" if info["passed"] else "❌ FAILED"
        print(f"  Tier {tier}: {info['name']} — {status}")
    print(f"\n  Total: {total_passed} passed, {total_failed} failed")
    print(f"{'='*60}\n")

    sys.exit(0 if total_failed == 0 else 1)


if __name__ == "__main__":
    main()
