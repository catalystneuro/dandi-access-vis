#!/usr/bin/env python3
"""
Create a static choropleth map showing total data downloaded by country from DANDI access summaries.
"""

from typing import Dict, List, Optional
import argparse
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import warnings

warnings.filterwarnings("ignore")
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from cartopy.io import shapereader

from map_utils import load_country_data, load_country_mapping, format_bytes


def create_choropleth(
    country_data: Dict[str, int],
    log_scale: bool = True,
    output_file: str = "choropleth_map.svg",
    dandiset_ids: Optional[List[str]] = None,
) -> None:
    """
    Create choropleth map using cartopy.

    Parameters
    ----------
    country_data : dict of str to int
        Dictionary mapping country codes to total bytes downloaded
    log_scale : bool, optional
        Whether to use logarithmic scale for colors, by default True
    output_file : str, optional
        Output filename for the map, by default 'choropleth_map.svg'
    dandiset_ids : list of str, optional
        List of dandiset IDs being visualized (for title), by default None

    Examples
    --------
    >>> country_data = {'US': 1000000000, 'DE': 500000000}
    >>> create_choropleth(country_data, log_scale=False, output_file='my_map.svg')
    """

    # Convert to DataFrame
    df = pd.DataFrame(
        list(country_data.items()), columns=["country", "bytes_downloaded"]
    )

    if df.empty:
        print("No data to visualize")
        return

    print(f"Found data for {len(df)} countries")

    # Map our 2-letter country codes to full country names
    country_mapping = load_country_mapping()
    df["country_name"] = df["country"].map(country_mapping)

    # Print mapping results for debugging
    mapped_count = df["country_name"].notna().sum()
    print(f"Successfully mapped {mapped_count} out of {len(df)} countries")

    # Create figure with cartopy projection
    fig = plt.figure(figsize=(20, 12))
    ax = plt.axes(projection=ccrs.PlateCarree())

    # Add natural features using cartopy
    ax.add_feature(cfeature.OCEAN, color="#e3f2fd", alpha=0.8)
    ax.add_feature(cfeature.LAKES, color="#b3e5fc", alpha=0.8)
    ax.add_feature(cfeature.RIVERS, color="#90caf9", linewidth=0.5)

    # Set global extent but exclude Antarctica
    ax.set_global()
    ax.set_ylim(-60, 85)  # Exclude Antarctica (below -60 latitude)

    # Get Natural Earth countries data
    countries = cfeature.NaturalEarthFeature(
        category="cultural",
        name="admin_0_countries",
        scale="50m",
        facecolor="lightgray",
    )

    # Add countries as base layer
    ax.add_feature(
        countries, facecolor="lightgray", edgecolor="white", linewidth=0.5, alpha=0.5
    )

    # Color countries with data
    # Get country geometries from Natural Earth
    reader = shapereader.Reader(
        shapereader.natural_earth("50m", "cultural", "admin_0_countries")
    )

    # Create a mapping from country names to data values
    country_data_dict = {}
    for _, row in df[df["country_name"].notna()].iterrows():
        country_data_dict[row["country_name"]] = row["bytes_downloaded"]

    # Apply log transformation if requested
    if log_scale and len(country_data_dict) > 0:
        plot_values = {k: np.log10(v + 1) for k, v in country_data_dict.items()}
        scale_label = "Log₁₀(Bytes Downloaded + 1)"
        vmin = min(plot_values.values())
        vmax = max(plot_values.values())
    else:
        plot_values = country_data_dict
        scale_label = "Bytes Downloaded"
        vmin = min(plot_values.values()) if plot_values else 0
        vmax = max(plot_values.values()) if plot_values else 1

    # Define color map
    from matplotlib.cm import YlOrRd
    from matplotlib.colors import Normalize

    norm = Normalize(vmin=vmin, vmax=vmax)
    cmap = YlOrRd

    countries_colored = 0

    # Create a comprehensive mapping from Natural Earth names to our data
    # First, create a reverse mapping from our mapped names to Natural Earth names
    our_to_natural_earth = {
        "USA": ["United States of America", "United States"],
        "England": ["United Kingdom", "Great Britain"],
        "Russia": ["Russian Federation"],
        "South Korea": ["Korea", "Republic of Korea"],
        "Czech Republic": ["Czechia", "Czech Republic"],
    }

    # Color each country based on data
    for record in reader.records():
        natural_earth_name = record.attributes["NAME"]

        plot_value = None

        # Direct match first
        if natural_earth_name in plot_values:
            plot_value = plot_values[natural_earth_name]
        else:
            # Check reverse mappings
            for our_name, ne_names in our_to_natural_earth.items():
                if natural_earth_name in ne_names and our_name in plot_values:
                    plot_value = plot_values[our_name]
                    break

        if plot_value is not None:
            color = cmap(norm(plot_value))
            countries_colored += 1
        else:
            color = "lightgray"

        ax.add_geometries(
            [record.geometry],
            ccrs.PlateCarree(),
            facecolor=color,
            edgecolor="white",
            linewidth=0.5,
            alpha=0.8,
        )

    print(f"Colored {countries_colored} countries on the map")

    # Add colorbar if we have data
    if len(plot_values) > 0:
        # Create colorbar positioned in Pacific Ocean
        cbar_ax = fig.add_axes([0.15, 0.25, 0.01, 0.2])  # Position in Pacific

        from matplotlib.cm import ScalarMappable

        sm = ScalarMappable(norm=norm, cmap=cmap)
        sm.set_array([])

        cbar = fig.colorbar(sm, cax=cbar_ax)
        cbar.ax.tick_params(
            labelsize=7, left=True, right=False, labelleft=True, labelright=False
        )
        cbar.ax.yaxis.set_label_position("left")

        # Define fixed tick values
        unit_values = [
            1024,
            1024**2,
            1024**3,
            1024**4,
            1024**5,
        ]  # 1KB, 1MB, 1GB, 1TB, 1PB
        unit_labels = ["1 KB", "1 MB", "1 GB", "1 TB", "1 PB"]

        # Get the range of actual data values
        min_val = min(country_data_dict.values()) if country_data_dict else 0
        max_val = max(country_data_dict.values()) if country_data_dict else 1

        if log_scale:
            # Convert unit values to log space
            min_log = np.log10(min_val + 1) if min_val > 0 else 0
            max_log = np.log10(max_val + 1)

            # Only include ticks that fall within our data range
            valid_ticks = []
            valid_labels = []
            for value, label in zip(unit_values, unit_labels):
                log_val = np.log10(value + 1)
                if min_log <= log_val <= max_log:
                    valid_ticks.append(log_val)
                    valid_labels.append(label)

            if valid_ticks:
                cbar.set_ticks(valid_ticks)
                cbar.set_ticklabels(valid_labels)
        else:
            # For linear scale, only include ticks within data range
            valid_ticks = []
            valid_labels = []
            for value, label in zip(unit_values, unit_labels):
                if min_val <= value <= max_val:
                    valid_ticks.append(value)
                    valid_labels.append(label)

            if valid_ticks:
                cbar.set_ticks(valid_ticks)
                cbar.set_ticklabels(valid_labels)

        # Add label to colorbar
        cbar.set_label("Data Downloaded", rotation=90, labelpad=10, fontsize=10)

    # Customize plot
    title = "DANDI Data Downloads by Country"
    if dandiset_ids:
        if len(dandiset_ids) == 1:
            title = f"DANDI Data Downloads by Country - Dandiset {dandiset_ids[0]}"
        else:
            title = f"DANDI Data Downloads by Country - {len(dandiset_ids)} Dandisets"
    ax.set_title(title, fontsize=20, fontweight="bold", pad=20)

    # Remove axis elements for cleaner look
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    # Add subtitle
    scale_type = "Logarithmic" if log_scale else "Linear"
    fig.suptitle(
        f"Scale: {scale_type} | Countries with data: {countries_colored}",
        fontsize=14,
        y=0.02,
    )

    plt.tight_layout()

    # Save with high DPI for publication quality
    plt.savefig(output_file, dpi=300, bbox_inches="tight", facecolor="white")
    print(f"Choropleth map saved as: {output_file}")

    # Also save as PDF
    pdf_file = output_file.replace(".svg", ".pdf")
    plt.savefig(pdf_file, dpi=300, bbox_inches="tight", facecolor="white")
    print(f"PDF version saved as: {pdf_file}")

    # Print summary statistics
    print(f"\nSummary Statistics:")
    print(f"Total countries: {len(df)}")
    print(f"Total data downloaded: {format_bytes(df['bytes_downloaded'].sum())}")
    print(f"Top 10 countries by download volume:")
    top_countries = df.nlargest(10, "bytes_downloaded")
    for _, row in top_countries.iterrows():
        print(f"  {row['country']}: {format_bytes(row['bytes_downloaded'])}")


def main() -> None:
    """
    Main function to parse arguments and create choropleth.

    Examples
    --------
    >>> # Run from command line
    >>> # python create_choropleth.py --dandiset 000026 --log-scale
    """
    parser = argparse.ArgumentParser(
        description="Create static choropleth map of DANDI downloads by country"
    )
    parser.add_argument(
        "--log-scale",
        "-l",
        action="store_true",
        help="Use logarithmic scale for colors (default: linear)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="output/choropleth_map.svg",
        help="Output file name (default: output/choropleth_map.svg)",
    )
    parser.add_argument(
        "--data-path",
        "-d",
        default="../access-summaries/content",
        help="Path to the access summaries data directory (default: ../access-summaries/content)",
    )
    parser.add_argument(
        "--dandiset",
        default=None,
        help="Specific dandiset ID(s) to process, comma-separated (default: process all dandisets)",
    )

    args = parser.parse_args()

    # Parse comma-separated dandisets
    dandiset_ids = None
    if args.dandiset:
        dandiset_ids = [d.strip() for d in args.dandiset.split(",") if d.strip()]

    # If dandisets specified and using default output path, append dandiset IDs
    if dandiset_ids and args.output == "output/choropleth_map.svg":
        base_name = args.output.replace(".svg", "")
        if len(dandiset_ids) == 1:
            args.output = f"{base_name}_{dandiset_ids[0]}.svg"
        else:
            dandiset_str = "_".join(dandiset_ids)
            # Truncate if too long for filesystem
            if len(dandiset_str) > 50:
                dandiset_str = f"{dandiset_ids[0]}_and_{len(dandiset_ids)-1}_others"
            args.output = f"{base_name}_{dandiset_str}.svg"

    if dandiset_ids:
        if len(dandiset_ids) == 1:
            print(
                f"Loading and processing country data for dandiset {dandiset_ids[0]}..."
            )
        else:
            print(
                f"Loading and processing country data for {len(dandiset_ids)} dandisets..."
            )
    else:
        print("Loading and processing country data for all dandisets...")
    country_data = load_country_data(args.data_path, dandiset_ids)

    if not country_data:
        print("No valid country data found!")
        return

    print(f"Found data for {len(country_data)} countries")

    print("Creating choropleth map...")
    create_choropleth(
        country_data,
        log_scale=args.log_scale,
        output_file=args.output,
        dandiset_ids=dandiset_ids,
    )


if __name__ == "__main__":
    main()
