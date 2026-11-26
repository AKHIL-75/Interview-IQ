import subprocess
import sys
import time

test_files = [
    "tests/test_phase4.py",
    "tests/test_phase5.py",
    "tests/test_phase6.py",
    "tests/test_skill_matching_taxonomy.py",
    "tests/test_phase7.py",
    "tests/test_phase8.py",
    "tests/test_phase10.py",
    "tests/test_phase9.py",
    "tests/test_phase9_overhaul.py",
    "tests/test_interview_flow.py",
    "tests/test_phase11_persistence.py",
    "tests/test_phase12_profile.py",
    "tests/test_phase12_token_refresh.py",
    "tests/test_phase13_history_analytics.py",
    "tests/verify_phase13_isolation_edge_cases.py",
    "tests/test_phase14_report_generation.py",
    "tests/test_phase15_stt.py",
    "tests/verify_phase15_integration.py",
]


print("=================================================================")
print("RUNNING ALL BACKEND REGRESSION TEST SUITES")
print("=================================================================")

results = {}
total_start = time.time()

for tf in test_files:
    start = time.time()
    res = subprocess.run([sys.executable, tf], capture_output=True, text=True)
    duration = time.time() - start
    passed = (res.returncode == 0)
    results[tf] = (passed, duration, res.stdout, res.stderr)
    status_str = "PASS" if passed else "FAIL"
    print(f"[{status_str}] {tf} ({duration:.1f}s)")
    if not passed:
        print("STDOUT:", res.stdout[-600:])
        print("STDERR:", res.stderr[-600:])

print("\n=================================================================")
print("REGRESSION SUMMARY")
print("=================================================================")
all_passed = True
for tf, (passed, duration, _, _) in results.items():
    status_str = "PASS" if passed else "FAIL"
    print(f"  {status_str:4s} | {tf:25s} | {duration:.1f}s")
    if not passed:
        all_passed = False

total_duration = time.time() - total_start
print(f"\nTotal time: {total_duration:.1f}s")
print(f"OVERALL STATUS: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")
print("=================================================================")

sys.exit(0 if all_passed else 1)
