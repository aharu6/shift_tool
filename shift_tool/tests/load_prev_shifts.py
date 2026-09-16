from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parents[2]))

from optimizer.night_shift.oncall_constraints import OncallConstraintsOptimizer


if __name__ == "__main__":
    main()