#!/usr/bin/env python3
"""
Shared utilities for creating DANDI access maps.
"""

from typing import Dict, List, Optional, Tuple, Union, Any
import pandas as pd
from pathlib import Path
import json
import yaml

# Single dictionary for all color specifications
COLOR_SPECS = {
    "low": {
        "fill": "#26c6da",  # Cyan
        "stroke": "#0097a7",  # Dark cyan
        "name": "Cyan",
        "label": "< 10 MB",
        "size": 20,
    },
    "medium": {
        "fill": "#66bb6a",  # Light green
        "stroke": "#388e3c",  # Dark green
        "name": "Green",
        "label": "10 MB - 10 GB",
        "size": 40,
    },
    "high": {
        "fill": "#ffca28",  # Yellow
        "stroke": "#f57f17",  # Dark yellow
        "name": "Yellow",
        "label": "10 GB - 10 TB",
        "size": 60,
    },
    "very-high": {
        "fill": "#ff7043",  # Orange-red
        "stroke": "#d84315",  # Dark orange-red
        "name": "Orange",
        "label": "> 10 TB",
        "size": 80,
    },
}


def load_region_data(
    data_path: str = "../access-summaries/content",
    dandiset_ids: Optional[List[str]] = None,
) -> Dict[str, int]:
    """
    Load and aggregate data from all by_region.tsv files.

    Parameters
    ----------
    data_path : str, optional
        Path to the access summaries data directory, by default '../access-summaries/content'
    dandiset_ids : list of str, optional
        Specific dandiset IDs to process. If None, processes all dandisets, by default None

    Returns
    -------
    dict of str to int
        Dictionary mapping region names to total bytes sent for that region

    Examples
    --------
    >>> region_data = load_region_data()
    >>> print(f"Found data for {len(region_data)} regions")

    >>> specific_dandisets = load_region_data(dandiset_ids=['000026', '000409'])
    >>> print(f"Processed specific dandisets: {list(specific_dandisets.keys())}")
    """
    region_totals = {}

    # Find all by_region.tsv files
    summaries_dir = Path(data_path) / "summaries"

    if not summaries_dir.exists():
        print("Error: content/summaries directory not found!")
        return {}

    dandisets_processed = 0
    requested_dandisets = set(dandiset_ids) if dandiset_ids else None
    found_dandisets = set()

    for dandiset_dir in summaries_dir.iterdir():
        if dandiset_dir.is_dir():
            # If specific dandisets requested, only process those
            if requested_dandisets and dandiset_dir.name not in requested_dandisets:
                continue

            region_file = dandiset_dir / "by_region.tsv"
            if region_file.exists():
                try:
                    df = pd.read_csv(region_file, sep="\t")
                    dandisets_processed += 1
                    found_dandisets.add(dandiset_dir.name)

                    for _, row in df.iterrows():
                        region = row["region"]
                        bytes_sent = row["bytes_sent"]

                        # Skip non-geographic regions but keep detailed regions
                        non_geographic = ["GitHub", "VPN", "bogon", "unknown"]
                        if region in non_geographic:
                            continue

                        region_totals[region] = (
                            region_totals.get(region, 0) + bytes_sent
                        )

                except Exception as e:
                    print(f"Error processing {region_file}: {e}")
                    continue

    if requested_dandisets:
        print(f"Processed dandisets: {', '.join(sorted(found_dandisets))}")
        missing = requested_dandisets - found_dandisets
        if missing:
            print(f"Warning: No data found for dandisets: {', '.join(sorted(missing))}")
    else:
        print(f"Processed {dandisets_processed} dandisets")

    return region_totals


def extract_country_code(region: str) -> Optional[str]:
    """
    Extract country code from region string.

    Parameters
    ----------
    region : str
        Region string that may contain country code and additional location info
        separated by forward slashes (e.g., 'US/California/Los Angeles')

    Returns
    -------
    str or None
        Two-letter country code if extractable, None if region is non-geographic

    Examples
    --------
    >>> extract_country_code('US/California/Los Angeles')
    'US'

    >>> extract_country_code('GitHub')
    None

    >>> extract_country_code('DE')
    'DE'
    """
    # Skip non-geographic regions
    non_geographic = ["AWS/", "GCP/", "GitHub", "VPN", "bogon", "unknown"]
    if any(region.startswith(ng) for ng in non_geographic):
        return None

    # Extract country code (everything before the first '/')
    if "/" in region:
        return region.split("/")[0]
    else:
        # Handle cases where region is just a country code
        return region


def load_country_data(
    data_path: str = "../access-summaries/content",
    dandiset_ids: Optional[List[str]] = None,
) -> Dict[str, int]:
    """
    Load and aggregate data by country from all by_region.tsv files.

    Parameters
    ----------
    data_path : str, optional
        Path to the access summaries data directory, by default '../access-summaries/content'
    dandiset_ids : list of str, optional
        Specific dandiset IDs to process. If None, processes all dandisets, by default None

    Returns
    -------
    dict of str to int
        Dictionary mapping country codes (2-letter) to total bytes sent for that country

    Examples
    --------
    >>> country_data = load_country_data()
    >>> print(f"Found data for {len(country_data)} countries")

    >>> specific_countries = load_country_data(dandiset_ids=['000026'])
    >>> total_us_downloads = specific_countries.get('US', 0)
    """
    country_totals = {}

    # Get region data first
    region_data = load_region_data(data_path, dandiset_ids)

    # Aggregate by country
    for region, bytes_sent in region_data.items():
        country = extract_country_code(region)
        if country:
            country_totals[country] = country_totals.get(country, 0) + bytes_sent

    return country_totals


def load_coordinates(
    data_path: str = "../access-summaries/content",
) -> Dict[str, Dict[str, Any]]:
    """
    Load coordinate data from YAML file.

    Parameters
    ----------
    data_path : str, optional
        Path to the access summaries data directory, by default '../access-summaries/content'

    Returns
    -------
    dict of str to dict
        Dictionary mapping region codes to coordinate dictionaries containing
        'latitude' and 'longitude' keys

    Examples
    --------
    >>> coords = load_coordinates()
    >>> us_coords = coords.get('US', {})
    >>> lat, lon = us_coords.get('latitude'), us_coords.get('longitude')
    """
    try:
        coordinates_file = Path(data_path) / "region_codes_to_coordinates.yaml"
        with open(coordinates_file, "r") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print("Error: region_codes_to_coordinates.yaml file not found!")
        return {}
    except yaml.YAMLError:
        print("Error: Invalid YAML in region_codes_to_coordinates.yaml!")
        return {}


def load_country_mapping() -> Dict[str, str]:
    """
    Load country mapping from JSON file.

    Returns
    -------
    dict of str to str
        Dictionary mapping 2-letter country codes to full country names

    Examples
    --------
    >>> mapping = load_country_mapping()
    >>> country_name = mapping.get('US', 'Unknown')
    >>> print(f"US maps to: {country_name}")
    """
    try:
        with open("country_mapping.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print("Error: country_mapping.json file not found!")
        return {}
    except json.JSONDecodeError:
        print("Error: Invalid JSON in country_mapping.json!")
        return {}


def format_bytes(bytes_value: Union[int, float]) -> str:
    """
    Format bytes in human readable format.

    Parameters
    ----------
    bytes_value : int or float
        Number of bytes to format

    Returns
    -------
    str
        Human-readable string representation of bytes (e.g., '1.23 GB')

    Examples
    --------
    >>> format_bytes(1024)
    '1.00 KB'

    >>> format_bytes(1073741824)
    '1.00 GB'

    >>> format_bytes(1234567890)
    '1.15 GB'
    """
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if bytes_value < 1024.0:
            return f"{bytes_value:.2f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.2f} EB"


def get_point_color_and_size(bytes_value: Union[int, float]) -> Tuple[str, str, int]:
    """
    Get color and size for point based on download volume.

    Parameters
    ----------
    bytes_value : int or float
        Number of bytes downloaded for determining color and size category

    Returns
    -------
    tuple of (str, str, int)
        Tuple containing (fill_color, stroke_color, size) for plotting points

    Examples
    --------
    >>> fill, stroke, size = get_point_color_and_size(5 * 1024 * 1024)  # 5 MB
    >>> print(f"5 MB gets: {fill} fill, {stroke} stroke, size {size}")

    >>> fill, stroke, size = get_point_color_and_size(50 * 1024**4)  # 50 TB
    >>> print(f"50 TB gets: {fill} fill, {stroke} stroke, size {size}")
    """
    # Color thresholds
    mb_10 = 10 * 1024 * 1024  # 10 MB
    gb_10 = 10 * 1024 * 1024 * 1024  # 10 GB
    tb_10 = 10 * 1024 * 1024 * 1024 * 1024  # 10 TB

    if bytes_value < mb_10:
        return (
            COLOR_SPECS["low"]["fill"],
            COLOR_SPECS["low"]["stroke"],
            COLOR_SPECS["low"]["size"],
        )
    elif bytes_value < gb_10:
        return (
            COLOR_SPECS["medium"]["fill"],
            COLOR_SPECS["medium"]["stroke"],
            COLOR_SPECS["medium"]["size"],
        )
    elif bytes_value < tb_10:
        return (
            COLOR_SPECS["high"]["fill"],
            COLOR_SPECS["high"]["stroke"],
            COLOR_SPECS["high"]["size"],
        )
    else:
        return (
            COLOR_SPECS["very-high"]["fill"],
            COLOR_SPECS["very-high"]["stroke"],
            COLOR_SPECS["very-high"]["size"],
        )
