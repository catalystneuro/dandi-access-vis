#!/usr/bin/env python3
"""
Create a scatter plot map showing total data downloaded by region with color-coded points.
Color scheme:
- < 10 MB: blue
- 10 MB to 10 GB: green
- 10 GB to 10 TB: yellow
- > 10 TB: red
"""

import argparse
import pandas as pd
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')
import cartopy.crs as ccrs
import cartopy.feature as cfeature

from map_utils import (
    COLOR_SPECS, 
    load_region_data, 
    load_coordinates, 
    get_point_color_and_size
)


def create_scatter_map(region_data, coordinates, output_file='scatter_map.svg', dandiset_ids=None):
    """Create scatter plot map using cartopy."""
    
    # Convert to DataFrame and merge with coordinates
    plot_data = []
    
    for region, bytes_downloaded in region_data.items():
        if region in coordinates:
            coord_data = coordinates[region]
            lat = coord_data.get('latitude')
            lon = coord_data.get('longitude')
            
            # Skip regions with null coordinates and Antarctica
            if lat is not None and lon is not None and float(lat) > -60:
                fill_color, edge_color, size = get_point_color_and_size(bytes_downloaded)
                plot_data.append({
                    'region': region,
                    'latitude': float(lat),
                    'longitude': float(lon),
                    'bytes_downloaded': bytes_downloaded,
                    'fill_color': fill_color,
                    'edge_color': edge_color,
                    'size': size
                })
    
    if not plot_data:
        print("No plottable data found")
        return
    
    df = pd.DataFrame(plot_data)
    # Sort by bytes_downloaded so larger values (red points) are plotted on top
    df = df.sort_values('bytes_downloaded', ascending=True)
    print(f"Found {len(df)} regions with coordinates and data")
    
    # Create figure with cartopy projection
    fig = plt.figure(figsize=(20, 12))
    ax = plt.axes(projection=ccrs.PlateCarree())
    
    # Add natural features using cartopy (all map features first, before scatter points)
    ax.add_feature(cfeature.LAND, color="#dde9de", alpha=0.8)
    ax.add_feature(cfeature.OCEAN, color='#e3f2fd', alpha=0.8)
    ax.add_feature(cfeature.COASTLINE, color='#666666', linewidth=0.5)
    ax.add_feature(cfeature.BORDERS, color='#999999', linewidth=0.3)
    ax.add_feature(cfeature.LAKES, color='#b3e5fc', alpha=0.8)
    ax.add_feature(cfeature.RIVERS, color='#90caf9', linewidth=0.5)
    ax.add_feature(cfeature.STATES, linestyle='--', linewidth=0.5, alpha=0.8, edgecolor='#cccccc')
    
    # Set global extent but exclude Antarctica
    ax.set_global()
    ax.set_ylim(-60, 85)  # Exclude Antarctica (below -60 latitude)
    
    # Plot scatter points in order of bytes_downloaded (smallest to largest)
    # This ensures larger values (red points) are on top
    for _, row in df.iterrows():
        ax.scatter(row['longitude'], row['latitude'], 
                  c=row['fill_color'], s=row['size'], alpha=0.7, 
                  edgecolors=row['edge_color'], linewidth=1.2,
                  transform=ccrs.PlateCarree(), zorder=10)  # High zorder to be on top
    
    # Customize plot
    title = 'DANDI Data Downloads by Region'
    if dandiset_ids:
        if len(dandiset_ids) == 1:
            title = f'DANDI Data Downloads by Region - Dandiset {dandiset_ids[0]}'
        else:
            title = f'DANDI Data Downloads by Region - {len(dandiset_ids)} Dandisets'
    ax.set_title(title, fontsize=20, fontweight='bold', pad=20)
    
    # Calculate counts for legend
    low_count = len(df[df['fill_color'] == COLOR_SPECS['low']['fill']])
    medium_count = len(df[df['fill_color'] == COLOR_SPECS['medium']['fill']])
    high_count = len(df[df['fill_color'] == COLOR_SPECS['high']['fill']])
    very_high_count = len(df[df['fill_color'] == COLOR_SPECS['very-high']['fill']])
    
    # Create custom legend with counts in parentheses and correct sizes
    legend_elements = [
        plt.scatter([], [], c=COLOR_SPECS['low']['fill'], s=COLOR_SPECS['low']['size'], label=f"{COLOR_SPECS['low']['label']} ({low_count})", edgecolors=COLOR_SPECS['low']['stroke']),
        plt.scatter([], [], c=COLOR_SPECS['medium']['fill'], s=COLOR_SPECS['medium']['size'], label=f"{COLOR_SPECS['medium']['label']} ({medium_count})", edgecolors=COLOR_SPECS['medium']['stroke']),
        plt.scatter([], [], c=COLOR_SPECS['high']['fill'], s=COLOR_SPECS['high']['size'], label=f"{COLOR_SPECS['high']['label']} ({high_count})", edgecolors=COLOR_SPECS['high']['stroke']),
        plt.scatter([], [], c=COLOR_SPECS['very-high']['fill'], s=COLOR_SPECS['very-high']['size'], label=f"{COLOR_SPECS['very-high']['label']} ({very_high_count})", edgecolors=COLOR_SPECS['very-high']['stroke'])
    ]
    ax.legend(handles=legend_elements, loc='lower left', fontsize=12, 
              title='Download Volume', title_fontsize=14)
    
    plt.tight_layout()
    
    # Save with high DPI for publication quality
    plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"Scatter map saved as: {output_file}")
    
    # Also save as PDF
    pdf_file = output_file.replace('.svg', '.pdf')
    plt.savefig(pdf_file, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"PDF version saved as: {pdf_file}")
    


def main():
    """Main function to parse arguments and create scatter map."""
    parser = argparse.ArgumentParser(description='Create scatter plot map of DANDI downloads by region')
    parser.add_argument('--output', '-o', default='output/scatter_map.svg',
                       help='Output file name (default: output/scatter_map.svg)')
    parser.add_argument('--data-path', '-d', default='../access-summaries/content',
                       help='Path to the access summaries data directory (default: ../access-summaries/content)')
    parser.add_argument('--dandiset', default=None,
                       help='Specific dandiset ID(s) to process, comma-separated (default: process all dandisets)')
    
    args = parser.parse_args()
    
    # Parse comma-separated dandisets
    dandiset_ids = None
    if args.dandiset:
        dandiset_ids = [d.strip() for d in args.dandiset.split(',') if d.strip()]
    
    # If dandisets specified and using default output path, append dandiset IDs
    if dandiset_ids and args.output == 'output/scatter_map.svg':
        base_name = args.output.replace('.svg', '')
        if len(dandiset_ids) == 1:
            args.output = f"{base_name}_{dandiset_ids[0]}.svg"
        else:
            dandiset_str = '_'.join(dandiset_ids)
            # Truncate if too long for filesystem
            if len(dandiset_str) > 50:
                dandiset_str = f"{dandiset_ids[0]}_and_{len(dandiset_ids)-1}_others"
            args.output = f"{base_name}_{dandiset_str}.svg"
    
    if dandiset_ids:
        if len(dandiset_ids) == 1:
            print(f"Loading region data for dandiset {dandiset_ids[0]}...")
        else:
            print(f"Loading region data for {len(dandiset_ids)} dandisets...")
    else:
        print("Loading region data for all dandisets...")
    region_data = load_region_data(args.data_path, dandiset_ids)
    
    if not region_data:
        print("No valid region data found!")
        return
    
    print(f"Found data for {len(region_data)} regions")
    
    print("Loading coordinate data...")
    coordinates = load_coordinates(args.data_path)
    
    if not coordinates:
        print("No coordinate data found!")
        return
    
    print(f"Found coordinates for {len(coordinates)} regions")
    
    print("Creating scatter map...")
    create_scatter_map(region_data, coordinates, args.output, dandiset_ids)


if __name__ == '__main__':
    main()
