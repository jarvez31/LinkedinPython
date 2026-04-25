#!/usr/bin/env python3
"""
Clean jobs with null or empty descriptions from LinkedIn scraper JSON files.
Usage: python clean_jobs.py
"""

import json
from pathlib import Path

# Data directory
DATA_DIR = Path("data")
JOBS_FILE = DATA_DIR / "linkedin_jobs.json"
SCORED_FILE = DATA_DIR / "linkedin_jobs_scored.json"

def clean_file(filepath):
    """Remove jobs with null/empty description from a JSON file."""
    if not filepath.exists():
        print(f"⚠ File not found: {filepath}")
        return 0
    
    with open(filepath) as f:
        jobs = json.load(f)
    
    original_count = len(jobs)
    
    # Filter: keep only jobs with non-empty description
    cleaned = [
        job for job in jobs
        if job.get("description") and job.get("description").strip()
    ]
    
    removed_count = original_count - len(cleaned)
    
    if removed_count > 0:
        with open(filepath, "w") as f:
            json.dump(cleaned, f, indent=2)
        print(f"✓ {filepath.name}")
        print(f"  Before: {original_count} jobs")
        print(f"  After:  {len(cleaned)} jobs")
        print(f"  Removed: {removed_count} jobs with null/empty description")
    else:
        print(f"✓ {filepath.name} — all jobs have descriptions")
    
    return removed_count

def main():
    print("Cleaning jobs with null/empty descriptions...\n")
    
    total_removed = 0
    
    # Clean main jobs file
    if JOBS_FILE.exists():
        total_removed += clean_file(JOBS_FILE)
        print()
    
    # Clean scored jobs file
    if SCORED_FILE.exists():
        total_removed += clean_file(SCORED_FILE)
        print()
    
    print(f"Summary: Removed {total_removed} total jobs with null/empty descriptions")

if __name__ == "__main__":
    main()
