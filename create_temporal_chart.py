#!/usr/bin/env python3
"""
Create a temporal visualization showing DANDI downloads over time as a stacked line chart.
Shows top N dandisets individually with others grouped under "Other".
"""

import argparse
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
import numpy as np
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

from map_utils import format_bytes


def load_temporal_data(data_path='../access-summaries/content', dandiset_ids=None):
    """Load temporal data from all by_day.tsv files."""
    temporal_data = {}
    
    # Find all by_day.tsv files
    summaries_dir = Path(data_path) / 'summaries'
    
    if not summaries_dir.exists():
        print("Error: summaries directory not found!")
        return {}
    
    dandisets_processed = 0
    requested_dandisets = set(dandiset_ids) if dandiset_ids else None
    found_dandisets = set()
    
    for dandiset_dir in summaries_dir.iterdir():
        if dandiset_dir.is_dir():
            # If specific dandisets requested, only process those
            if requested_dandisets and dandiset_dir.name not in requested_dandisets:
                continue
                
            day_file = dandiset_dir / 'by_day.tsv'
            if day_file.exists():
                try:
                    df = pd.read_csv(day_file, sep='\t')
                    df['date'] = pd.to_datetime(df['date'])
                    
                    # Store data for this dandiset
                    temporal_data[dandiset_dir.name] = df
                    dandisets_processed += 1
                    found_dandisets.add(dandiset_dir.name)
                    
                except Exception as e:
                    print(f"Error processing {day_file}: {e}")
                    continue
    
    if requested_dandisets:
        print(f"Processed temporal data for dandisets: {', '.join(sorted(found_dandisets))}")
        missing = requested_dandisets - found_dandisets
        if missing:
            print(f"Warning: No temporal data found for dandisets: {', '.join(sorted(missing))}")
    else:
        print(f"Processed temporal data for {dandisets_processed} dandisets")
    
    return temporal_data


def create_temporal_chart(temporal_data, top_n=10, output_file='temporal_chart.svg'):
    """Create stacked line chart showing downloads over time."""
    
    if not temporal_data:
        print("No temporal data to visualize")
        return
    
    print(f"Creating temporal visualization with top {top_n} dandisets...")
    
    # Calculate total bytes per dandiset to identify top N
    dandiset_totals = {}
    for dandiset_id, df in temporal_data.items():
        dandiset_totals[dandiset_id] = df['bytes_sent'].sum()
    
    # Sort dandisets by total volume and get top N
    sorted_dandisets = sorted(dandiset_totals.items(), key=lambda x: x[1], reverse=True)
    top_dandisets = [d[0] for d in sorted_dandisets[:top_n]]
    other_dandisets = [d[0] for d in sorted_dandisets[top_n:]]
    
    print(f"Top {top_n} dandisets by total volume:")
    for i, (dandiset_id, total_bytes) in enumerate(sorted_dandisets[:top_n], 1):
        print(f"  {i}. {dandiset_id}: {format_bytes(total_bytes)}")
    
    if other_dandisets:
        other_total = sum(dandiset_totals[d] for d in other_dandisets)
        print(f"  Other ({len(other_dandisets)} dandisets): {format_bytes(other_total)}")
    
    # Create a complete date range from earliest to latest date across all dandisets
    all_dates = []
    for df in temporal_data.values():
        all_dates.extend(df['date'].tolist())
    
    if not all_dates:
        print("No dates found in temporal data")
        return
    
    min_date = min(all_dates)
    max_date = max(all_dates)
    date_range = pd.date_range(start=min_date, end=max_date, freq='D')
    
    # Create DataFrame with all dates and dandisets
    chart_data = pd.DataFrame(index=date_range)
    
    # Add top dandisets as individual columns
    for dandiset_id in top_dandisets:
        df = temporal_data[dandiset_id].set_index('date')
        chart_data[dandiset_id] = df['bytes_sent'].reindex(date_range, fill_value=0)
    
    # Add "Other" column combining remaining dandisets
    if other_dandisets:
        other_series = pd.Series(0, index=date_range)
        for dandiset_id in other_dandisets:
            df = temporal_data[dandiset_id].set_index('date')
            other_series += df['bytes_sent'].reindex(date_range, fill_value=0)
        chart_data['Other'] = other_series
    
    # Convert to GB for better readability
    chart_data_gb = chart_data / (1024**3)  # Convert bytes to GB
    
    # Create the plot
    fig, ax = plt.subplots(figsize=(16, 10))
    
    # Define color palette - use colorbrewer Set3 for good distinction
    colors = ['#8dd3c7', '#ffffb3', '#bebada', '#fb8072', '#80b1d3', 
              '#fdb462', '#b3de69', '#fccde5', '#d9d9d9', '#bc80bd', 
              '#ccebc5', '#ffed6f']
    
    # If we have "Other", make it gray
    if 'Other' in chart_data_gb.columns:
        column_colors = {col: colors[i % len(colors)] for i, col in enumerate(chart_data_gb.columns[:-1])}
        column_colors['Other'] = '#999999'  # Gray for "Other"
    else:
        column_colors = {col: colors[i % len(colors)] for i, col in enumerate(chart_data_gb.columns)}
    
    # Create stacked area plot
    ax.stackplot(chart_data_gb.index, 
                *[chart_data_gb[col] for col in chart_data_gb.columns],
                labels=chart_data_gb.columns,
                colors=[column_colors[col] for col in chart_data_gb.columns],
                alpha=0.8)
    
    # Customize the plot
    ax.set_title('DANDI Downloads Over Time by Dandiset', fontsize=18, fontweight='bold', pad=20)
    ax.set_xlabel('Date', fontsize=14)
    ax.set_ylabel('Daily Downloads (GB)', fontsize=14)
    
    # Format x-axis
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_minor_locator(mdates.MonthLocator([1, 4, 7, 10]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.xaxis.set_minor_formatter(mdates.DateFormatter('%b'))
    
    # Rotate x-axis labels for better readability
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=0)
    plt.setp(ax.xaxis.get_minorticklabels(), rotation=45, fontsize=8)
    
    # Format y-axis with scientific notation for large numbers
    ax.ticklabel_format(style='scientific', axis='y', scilimits=(0,0))
    
    # Add legend
    handles, labels = ax.get_legend_handles_labels()
    # Reverse to match stacking order (top to bottom)
    ax.legend(list(reversed(handles)), list(reversed(labels)), 
             loc='upper left', bbox_to_anchor=(0, 1), 
             frameon=True, fancybox=True, shadow=True)
    
    # Add grid for better readability
    ax.grid(True, alpha=0.3, linestyle='--')
    
    # Set y-axis to start at 0
    ax.set_ylim(bottom=0)
    
    # Tight layout
    plt.tight_layout()
    
    # Save with high DPI for publication quality
    plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"Temporal chart saved as: {output_file}")
    
    # Also save as PDF
    pdf_file = output_file.replace('.svg', '.pdf')
    plt.savefig(pdf_file, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"PDF version saved as: {pdf_file}")
    
    # Print summary statistics
    print(f"\nSummary Statistics:")
    total_dandisets = len(temporal_data)
    print(f"Total dandisets analyzed: {total_dandisets}")
    print(f"Date range: {min_date.strftime('%Y-%m-%d')} to {max_date.strftime('%Y-%m-%d')}")
    
    total_data = sum(dandiset_totals.values())
    print(f"Total data across all time: {format_bytes(total_data)}")
    
    # Peak day statistics
    daily_totals = chart_data.sum(axis=1)
    peak_day = daily_totals.idxmax()
    peak_amount = daily_totals.max()
    print(f"Peak download day: {peak_day.strftime('%Y-%m-%d')} ({format_bytes(peak_amount)})")


def main():
    """Main function to parse arguments and create temporal chart."""
    parser = argparse.ArgumentParser(description='Create temporal visualization of DANDI downloads over time')
    parser.add_argument('--output', '-o', default='output/temporal_chart.svg',
                       help='Output file name (default: output/temporal_chart.svg)')
    parser.add_argument('--data-path', '-d', default='../access-summaries/content',
                       help='Path to the access summaries data directory (default: ../access-summaries/content)')
    parser.add_argument('--dandiset', default=None,
                       help='Specific dandiset ID(s) to process, comma-separated (default: process all dandisets)')
    parser.add_argument('--top-n', '-n', type=int, default=10,
                       help='Number of top dandisets to show individually (default: 10)')
    
    args = parser.parse_args()
    
    # Parse comma-separated dandisets
    dandiset_ids = None
    if args.dandiset:
        dandiset_ids = [d.strip() for d in args.dandiset.split(',') if d.strip()]
    
    # If dandisets specified and using default output path, append identifier
    if dandiset_ids and args.output == 'output/temporal_chart.svg':
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
            print(f"Loading temporal data for dandiset {dandiset_ids[0]}...")
        else:
            print(f"Loading temporal data for {len(dandiset_ids)} dandisets...")
    else:
        print("Loading temporal data for all dandisets...")
    
    temporal_data = load_temporal_data(args.data_path, dandiset_ids)
    
    if not temporal_data:
        print("No valid temporal data found!")
        return
    
    print("Creating temporal chart...")
    create_temporal_chart(temporal_data, top_n=args.top_n, output_file=args.output)


if __name__ == '__main__':
    main()
