import sys
import traceback

try:
    import main
    print("SUCCESS: main imported successfully")
except Exception as e:
    print(f"ERROR: {e}")
    traceback.print_exc()
