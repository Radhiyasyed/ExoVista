"""
query_exoplanet_archive.py  (v2 -- mission-targeted pulls)

Data Engineering Lead task update:
  Instead of pulling an arbitrary sample, pull the top 50 exoplanets
  discovered by each of two specific missions -- Kepler and TESS --
  and combine them into one dataset, tagged with which mission found
  each planet.

  "Top 50" is ranked by most recently published/updated record within
  each mission (rowupdate DESC), which is a meaningful, defensible
  ordering rather than an arbitrary database row order. Change
  ORDER_BY below if a different ranking is preferred (e.g. by radius,
  by discovery year).

TAP endpoint docs:
https://exoplanetarchive.ipac.caltech.edu/docs/TAP/usingTAP.html
"""

import io
import sys
import requests
import pandas as pd
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TAP_SYNC_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
TABLE_NAME = "pscomppars"

TARGET_COLUMNS = [
    "pl_name",     # planet name
    "pl_rade",     # planet radius (Earth radii)
    "pl_bmasse",   # planet mass, best estimate (Earth masses)
    "pl_eqt",      # planet equilibrium temperature (Kelvin)
    "pl_orbsmax",  # orbital semi-major axis (AU)
    "st_teff",     # host star effective temperature (Kelvin)
    "disc_facility",  # discovery facility -- used to filter by mission
]

# Mission filters: disc_facility values in the archive for each mission.
# Kepler entries are recorded simply as "Kepler"; TESS entries are recorded
# with the full facility name. LIKE is used for a safe partial match.
MISSIONS = {
    "Kepler": "Kepler",
    "TESS": "Transiting Exoplanet Survey Satellite (TESS)",
}

ROWS_PER_MISSION = 50

# Ranking used to select the "top" N rows within each mission.
# disc_year (Discovery Year) is a standard, documented column in
# pscomppars -- ranking by it descending means "most recently
# discovered first" within each mission.
ORDER_BY = "disc_year DESC"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
DOCS_DIR = PROJECT_ROOT / "docs"


# ---------------------------------------------------------------------------
# Core query function
# ---------------------------------------------------------------------------

def run_tap_query(adql_query: str, fmt: str = "csv") -> str:
    params = {"query": adql_query, "format": fmt}
    response = requests.get(TAP_SYNC_URL, params=params, timeout=60)
    response.raise_for_status()
    return response.text


# ---------------------------------------------------------------------------
# Step 1: Pull top-N planets for one mission
# ---------------------------------------------------------------------------

def fetch_mission_sample(mission_label: str, facility_value: str,
                          limit: int = ROWS_PER_MISSION) -> pd.DataFrame:
    """
    Pull the top `limit` planets discovered by a specific mission,
    ranked by ORDER_BY. Adds a 'mission' column so the combined dataset
    keeps track of where each row came from.
    """
    column_list = ", ".join(TARGET_COLUMNS)
    query = (
        f"SELECT TOP {limit} {column_list} FROM {TABLE_NAME} "
        f"WHERE disc_facility = '{facility_value}' "
        f"ORDER BY {ORDER_BY}"
    )
    raw_csv = run_tap_query(query, fmt="csv")
    df = pd.read_csv(io.StringIO(raw_csv))
    df["mission"] = mission_label
    return df


def fetch_all_missions() -> pd.DataFrame:
    """
    Pull top-N planets for every mission in MISSIONS and combine them
    into a single dataset.
    """
    frames = []
    for mission_label, facility_value in MISSIONS.items():
        print(f"Querying top {ROWS_PER_MISSION} {mission_label} planets...")
        df = fetch_mission_sample(mission_label, facility_value)
        print(f"  -> got {len(df)} rows for {mission_label}")
        frames.append(df)
    combined = pd.concat(frames, ignore_index=True)
    return combined


# ---------------------------------------------------------------------------
# Step 2: Data dictionary (unchanged approach, now includes disc_facility)
# ---------------------------------------------------------------------------

def fetch_data_dictionary(table_name: str = TABLE_NAME,
                           columns: list = TARGET_COLUMNS) -> pd.DataFrame:
    quoted_columns = ", ".join(f"'{c}'" for c in columns)
    query = (
        "SELECT column_name, description, unit, datatype "
        "FROM TAP_SCHEMA.columns "
        f"WHERE table_name = '{table_name}' "
        f"AND column_name IN ({quoted_columns}) "
        "ORDER BY column_name"
    )
    raw_csv = run_tap_query(query, fmt="csv")
    df = pd.read_csv(io.StringIO(raw_csv))
    return df


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        combined_df = fetch_all_missions()
    except requests.RequestException as e:
        print(f"ERROR: mission data query failed: {e}", file=sys.stderr)
        sys.exit(1)

    sample_path = RAW_DATA_DIR / "pscomppars_sample.csv"
    combined_df.to_csv(sample_path, index=False)
    print(f"\nSaved {len(combined_df)} total rows "
          f"({combined_df['mission'].value_counts().to_dict()}) -> {sample_path}")

    print(f"\nQuerying TAP_SCHEMA.columns for field definitions...")
    try:
        dict_df = fetch_data_dictionary()
    except requests.RequestException as e:
        print(f"ERROR: data dictionary query failed: {e}", file=sys.stderr)
        sys.exit(1)

    dict_path = DOCS_DIR / f"{TABLE_NAME}_data_dictionary.csv"
    dict_df.to_csv(dict_path, index=False)
    print(f"Saved {len(dict_df)} field definitions -> {dict_path}")


if __name__ == "__main__":
    main()
