# DANDI Access Visualization Tools

This repository contains tools for creating geographic visualizations of DANDI data access patterns, including choropleth maps and scatter plots showing data download patterns by country and region.

## Features

- **Choropleth Maps**: Country-level data visualization with color-coded regions
- **Scatter Maps**: Region-level visualization with proportional point sizes
- **Multiple Dandiset Support**: Process specific dandisets or combinations of dandisets
- **Flexible Data Paths**: Configure custom data directory locations
- **Centralized Styling**: Consistent color schemes across all visualizations
- **Publication Quality**: High-resolution SVG and PDF outputs
- **Flexible Scaling**: Linear and logarithmic scale options

## Installation

Navigate to the visualization directory and install dependencies:

```bash
cd visualization
pip install -r requirements.txt
```

### Dependencies
- **pandas**: Data manipulation
- **matplotlib**: Plotting framework
- **numpy**: Numerical operations
- **cartopy**: Geographic projections and mapping
- **pyyaml**: YAML configuration file parsing

## Usage

### Basic Usage

#### All Dandisets (Default)
```bash
# Process all available dandisets
python create_choropleth.py --log-scale
```

**Creates:** Global country-level visualization showing 7.69 PB across 117 countries

![Global Choropleth Map](output/choropleth_map.svg)

*Global DANDI downloads by country (logarithmic scale) - showing Netherlands and US as top consumers*

#### Single Dandiset
```bash
# Process specific dandiset with automatic filename
python create_choropleth.py --dandiset 000026 --log-scale
```

**Creates:** Focused view of single dandiset (114.23 TB across 44 countries)

![Single Dandiset Choropleth](output/choropleth_map_000026.svg)

*Dandiset 000026 downloads by country - US and Netherlands dominate usage*

#### Multiple Dandisets
```bash
# Process multiple specific dandisets
python create_scatter_map.py --dandiset 000026,000409,000488
```

**Creates:** Regional scatter plot showing precise geographic distribution

![Multi-Dandiset Scatter Map](output/scatter_map_000026_000409_000488.svg)

*Combined regional view of 3 dandisets - points show both location and download volume with color/size coding*

### Command Reference

#### Choropleth Maps (Country-level)

```bash
python create_choropleth.py [options]

Options:
  --log-scale, -l          Use logarithmic scale (recommended for wide ranges)
  --output, -o FILE        Output filename (default: output/choropleth_map.svg)
  --data-path, -d PATH     Data directory (default: ../access-summaries/content)
  --dandiset DANDISETS     Comma-separated dandiset IDs (default: all)
  --help                   Show help message
```

#### Scatter Maps (Region-level)

```bash
python create_scatter_map.py [options]

Options:
  --output, -o FILE        Output filename (default: output/scatter_map.svg)
  --data-path, -d PATH     Data directory (default: ../access-summaries/content)
  --dandiset DANDISETS     Comma-separated dandiset IDs (default: all)
  --help                   Show help message
```


## Output Files

Both scripts generate:
- **SVG files**: Vector format for publications (300 DPI equivalent)
- **PDF files**: Alternative format for presentations
- **Console output**: Summary statistics and processing information

