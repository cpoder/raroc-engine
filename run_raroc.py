#!/usr/bin/env python3
"""RAROC Engine - convenience launcher.

Usage:
    python3 run_raroc.py demo                           # Run demo scenarios
    python3 run_raroc.py calc -p mlt_credit -d 35e6 ... # Calculate single deal
    python3 run_raroc.py batch deals.csv -o results.xlsx # Batch processing
    python3 run_raroc.py sensitivity --parameter grr     # Sensitivity analysis
    python3 run_raroc.py ratings                         # Show rating table
    python3 run_raroc.py products                        # Show product types
    python3 run_raroc.py settings                        # Show study settings

    Add --regime basel2 for original Basel II mode (default: basel3).
"""

from raroc_engine.cli import main

if __name__ == "__main__":
    main()
