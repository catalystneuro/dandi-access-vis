#!/usr/bin/env python3
"""
Create a static choropleth map showing total data downloaded by admin-1 subdivisions (states/provinces).
Uses GADM (Global Administrative Areas) dataset for better GeoIP name matching.
"""

from typing import Dict, List, Optional
import argparse
import json
import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import warnings
import zipfile
import urllib.request
from pathlib import Path
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable
from tqdm import tqdm

warnings.filterwarnings("ignore")

from map_utils import load_region_data, load_country_mapping, format_bytes


def parse_bytes_string(s: str) -> int:
    """
    Parse a human-readable byte string like '10TB' or '500GB' into bytes.
    
    Parameters
    ----------
    s : str
        String like '10TB', '500GB', '1PB', '100MB', '50KB'
        
    Returns
    -------
    int
        Number of bytes
    """
    s = s.strip().upper()
    units = {
        'B': 1,
        'KB': 1024,
        'MB': 1024 ** 2,
        'GB': 1024 ** 3,
        'TB': 1024 ** 4,
        'PB': 1024 ** 5,
    }
    
    for unit, multiplier in sorted(units.items(), key=lambda x: -len(x[0])):
        if s.endswith(unit):
            number_part = s[:-len(unit)].strip()
            try:
                return int(float(number_part) * multiplier)
            except ValueError:
                raise ValueError(f"Invalid number in byte string: {s}")
    
    # If no unit, try to parse as raw bytes
    try:
        return int(s)
    except ValueError:
        raise ValueError(f"Invalid byte string format: {s}. Use format like '10TB', '500GB', etc.")

# GADM data configuration
GADM_DATA_DIR = Path("data/gadm")
GADM_GPKG_URL = "https://geodata.ucdavis.edu/gadm/gadm4.1/gadm_410-gpkg.zip"
GADM_GPKG_FILE = "gadm_410.gpkg"


def download_gadm_data() -> Path:
    """
    Download and cache GADM world data.
    
    Returns
    -------
    Path
        Path to the GADM GeoPackage file
    """
    gpkg_path = GADM_DATA_DIR / GADM_GPKG_FILE
    
    if gpkg_path.exists():
        print(f"Using cached GADM data: {gpkg_path}")
        return gpkg_path
    
    # Create data directory
    GADM_DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    zip_path = GADM_DATA_DIR / "gadm_410-gpkg.zip"
    
    print(f"Downloading GADM world data (~1.4GB)...")
    print(f"This is a one-time download and will be cached for future use.")
    print(f"URL: {GADM_GPKG_URL}")
    
    # Download with progress
    def show_progress(block_num, block_size, total_size):
        downloaded = block_num * block_size
        percent = min(100, downloaded * 100 / total_size)
        mb_downloaded = downloaded / (1024 * 1024)
        mb_total = total_size / (1024 * 1024)
        print(f"\rDownloading: {mb_downloaded:.1f}/{mb_total:.1f} MB ({percent:.1f}%)", end="", flush=True)
    
    urllib.request.urlretrieve(GADM_GPKG_URL, zip_path, show_progress)
    print("\nDownload complete.")
    
    # Extract GeoPackage
    print("Extracting GeoPackage...")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(GADM_DATA_DIR)
    
    # Remove zip file to save space
    zip_path.unlink()
    print(f"GADM data ready: {gpkg_path}")
    
    return gpkg_path


def load_gadm_admin1() -> gpd.GeoDataFrame:
    """
    Load GADM admin-1 (state/province) boundaries.
    
    The GADM 4.1 GeoPackage contains all admin levels in a single layer.
    We need to dissolve by GID_1 to get admin-1 boundaries.
    
    Returns
    -------
    GeoDataFrame
        GADM admin-1 boundaries with COUNTRY, NAME_1 (subdivision), GID_0 (country code)
    """
    gpkg_path = download_gadm_data()
    
    print("Loading GADM admin-1 boundaries...")
    
    # Check for cached dissolved admin-1 file
    cache_path = GADM_DATA_DIR / "gadm_410_admin1.gpkg"
    if cache_path.exists():
        print(f"Using cached admin-1 data: {cache_path}")
        gdf = gpd.read_file(cache_path)
        print(f"Loaded {len(gdf)} admin-1 subdivisions")
        return gdf
    
    # Load full GADM data from single layer
    print("Loading full GADM data (this may take a moment)...")
    gdf = gpd.read_file(gpkg_path, layer="gadm_410")
    print(f"Loaded {len(gdf)} detailed polygons")
    
    # Dissolve to admin-1 level by GID_1 with progress tracking
    print("Dissolving to admin-1 level...")
    
    # Get unique GID_1 values for progress tracking
    unique_gid1 = gdf['GID_1'].unique()
    print(f"Processing {len(unique_gid1)} admin-1 regions...")
    
    # Dissolve in chunks with progress bar
    dissolved_parts = []
    for gid1 in tqdm(unique_gid1, desc="Dissolving regions", unit="region"):
        subset = gdf[gdf['GID_1'] == gid1]
        if len(subset) > 0:
            dissolved = subset.dissolve(
                by='GID_1',
                aggfunc={
                    'GID_0': 'first',
                    'COUNTRY': 'first',
                    'NAME_1': 'first',
                    'NAME_0': 'first',
                }
            )
            dissolved_parts.append(dissolved)
    
    # Combine all dissolved parts
    admin1 = pd.concat(dissolved_parts).reset_index()
    
    print(f"Created {len(admin1)} admin-1 subdivisions")
    
    # Save cached version for future use
    print(f"Caching admin-1 data to: {cache_path}")
    admin1.to_file(cache_path, driver="GPKG")
    
    return admin1


def create_subdivision_choropleth(
    region_data: Dict[str, int],
    log_scale: bool = True,
    output_file: str = "output/subdivision_choropleth.svg",
    dandiset_ids: Optional[List[str]] = None,
    dry_run: bool = False,
    max_bytes: Optional[int] = None,
    vertical_colorbar: bool = False,
) -> None:
    """
    Create choropleth map showing data downloaded by admin-1 subdivisions worldwide.

    Parameters
    ----------
    region_data : dict of str to int
        Dictionary mapping region codes to total bytes downloaded
    log_scale : bool, optional
        Whether to use logarithmic scale for colors, by default True
    output_file : str, optional
        Output filename for the map, by default 'output/subdivision_choropleth.svg'
    dandiset_ids : list of str, optional
        List of dandiset IDs being visualized (for title), by default None
    max_bytes : int, optional
        Maximum bytes value for color scale. Values above this are capped.
        If None (default), uses the maximum value in the data.
    vertical_colorbar : bool, optional
        If True, place colorbar vertically on the right side. By default False
        (horizontal colorbar at the bottom).

    Examples
    --------
    >>> region_data = {'US/California': 1000000000, 'DE/Bavaria': 500000000}
    >>> create_subdivision_choropleth(region_data, log_scale=True, output_file='my_map.svg')
    >>> # With max cap at 10TB:
    >>> create_subdivision_choropleth(region_data, max_bytes=10 * 1024**4)
    >>> # Dry run to test matching without plotting:
    >>> create_subdivision_choropleth(region_data, dry_run=True)
    """
    # Load GADM data
    world_admin1 = load_gadm_admin1()

    # Load country mapping for matching (2-letter codes to names)
    country_mapping = load_country_mapping()
    # Create reverse mapping from full name to code
    name_to_code = {v: k for k, v in country_mapping.items()}
    
    # GADM uses 3-letter ISO codes (GID_0), create mapping from 2-letter to 3-letter
    # Also create mapping from country name to 2-letter code
    iso2_to_iso3 = {}
    for _, row in world_admin1.drop_duplicates('GID_0').iterrows():
        country_name = row['COUNTRY']
        gid_0 = row['GID_0']  # 3-letter code
        # Try to find 2-letter code from our mapping
        if country_name in name_to_code:
            iso2_to_iso3[name_to_code[country_name]] = gid_0
    
    # Add common mappings that might be missing
    common_iso_mappings = {
        'US': 'USA', 'GB': 'GBR', 'DE': 'DEU', 'FR': 'FRA', 'IT': 'ITA',
        'CA': 'CAN', 'AU': 'AUS', 'JP': 'JPN', 'CN': 'CHN', 'IN': 'IND',
        'BR': 'BRA', 'RU': 'RUS', 'NL': 'NLD', 'CH': 'CHE', 'SE': 'SWE',
        'ES': 'ESP', 'KR': 'KOR', 'TW': 'TWN', 'HK': 'HKG', 'SG': 'SGP',
        'AT': 'AUT', 'BE': 'BEL', 'DK': 'DNK', 'FI': 'FIN', 'NO': 'NOR',
        'PL': 'POL', 'PT': 'PRT', 'CZ': 'CZE', 'IE': 'IRL', 'NZ': 'NZL',
        'IL': 'ISR', 'MX': 'MEX', 'AR': 'ARG', 'CL': 'CHL', 'CO': 'COL',
        'ZA': 'ZAF', 'EG': 'EGY', 'KE': 'KEN', 'NG': 'NGA', 'MY': 'MYS',
        'TH': 'THA', 'VN': 'VNM', 'PH': 'PHL', 'ID': 'IDN', 'PK': 'PAK',
        'BD': 'BGD', 'IR': 'IRN', 'SA': 'SAU', 'AE': 'ARE', 'TR': 'TUR',
        'GR': 'GRC', 'HU': 'HUN', 'RO': 'ROU', 'UA': 'UKR', 'CY': 'CYP',
        'LU': 'LUX', 'SK': 'SVK', 'SI': 'SVN', 'EE': 'EST', 'LV': 'LVA',
        'LT': 'LTU', 'HR': 'HRV', 'RS': 'SRB', 'BG': 'BGR', 'KW': 'KWT',
        'CI': 'CIV', 'MT': 'MLT', 'JM': 'JAM', 'JO': 'JOR', 'ET': 'ETH',
        'MG': 'MDG', 'GP': 'GLP', 'RE': 'REU', 'KZ': 'KAZ', 'SY': 'SYR',
        'MD': 'MDA', 'YE': 'YEM', 'VG': 'VGB', 'OM': 'OMN', 'AZ': 'AZE',
        'TL': 'TLS',
    }
    iso2_to_iso3.update(common_iso_mappings)

    # Special country code remapping (e.g., HK -> CN for Hong Kong)
    # Format: {input_country_code: (gadm_country_code, gadm_region_name_or_None)}
    country_remapping = {
        'HK': ('CN', 'Hong Kong'),  # Hong Kong is admin-1 under China in GADM
        'SG': ('SG', None),  # Singapore - aggregate all to Singapore (no admin-1 match needed)
        'MO': ('CN', 'Macau'),  # Macau is admin-1 under China in GADM (no admin-1 subdivisions)
        'MK': ('MK', None),  # North Macedonia uses municipalities, not admin-1 - aggregate to country
        'XK': ('XK', None),  # Kosovo - not in GADM, aggregate to country level
        'NU': ('NU', None),  # Niue - small island nation, aggregate to country level
        'MQ': ('MQ', None),  # Martinique - French overseas territory, aggregate to country level
        'CW': ('CW', None),  # Curaçao - Dutch Caribbean territory, aggregate to country level
        'MV': ('MV', None),  # Maldives - not in GADM, aggregate to country level
    }

    # Parse region data to extract subdivision-level data
    # Region format: "CC/State/City" or "CC/State" or "CC"
    # Skip cloud provider regions (AWS, GCP)
    subdivision_data = {}
    cloud_data = {}
    aggregated_country_data = {}  # For countries without admin-1 matching
    
    for region, bytes_val in region_data.items():
        parts = region.split("/")
        if len(parts) >= 2:
            country_code = parts[0]
            # Skip cloud provider regions
            if country_code in ("AWS", "GCP"):
                cloud_data[region] = cloud_data.get(region, 0) + bytes_val
                continue
            
            subdivision_name = parts[1]
            
            # Check for country remapping
            if country_code in country_remapping:
                new_country, fixed_region = country_remapping[country_code]
                if fixed_region:
                    # Map all subdivisions to a single admin-1 region
                    key = f"{new_country}/{fixed_region}"
                    subdivision_data[key] = subdivision_data.get(key, 0) + bytes_val
                else:
                    # Aggregate to country level (no admin-1 available)
                    aggregated_country_data[country_code] = aggregated_country_data.get(country_code, 0) + bytes_val
                continue
            
            key = f"{country_code}/{subdivision_name}"
            subdivision_data[key] = subdivision_data.get(key, 0) + bytes_val

    print(f"\nFound data for {len(subdivision_data)} unique subdivisions")
    if cloud_data:
        print(f"Skipped {len(cloud_data)} cloud provider regions (AWS/GCP)")

    # Name aliases to map English names to GADM local names
    # Format: {country_code: {english_name: gadm_name}}
    # CONSOLIDATED - no duplicate country keys allowed
    name_aliases = {
        'NL': {
            'north holland': 'noord-holland',
            'south holland': 'zuid-holland',
            'friesland': 'fryslân',
            'north brabant': 'noord-brabant',
            'limburg': 'limburg',
        },
        'IT': {
            'tuscany': 'toscana',
            'lombardy': 'lombardia',
            'piedmont': 'piemonte',
            'sardinia': 'sardegna',
            'apulia': 'puglia',
            'sicily': 'sicilia',
            'venice': 'veneto',
        },
        'DE': {
            'north rhine-westphalia': 'nordrhein-westfalen',
            'north rhine westphalia': 'nordrhein-westfalen',
            'bavaria': 'bayern',
            'hesse': 'hessen',
            'lower saxony': 'niedersachsen',
            'saxony': 'sachsen',
            'rhineland-palatinate': 'rheinland-pfalz',
            'saxony-anhalt': 'sachsen-anhalt',
            'thuringia': 'thüringen',
        },
        'ES': {
            'balearic islands': 'islas baleares',
            'catalonia': 'cataluña',
            'basque country': 'país vasco',
            'andalusia': 'andalucía',
            'valencia': 'comunitat valenciana',
            'canary islands': 'islas canarias',
            'castille and león': 'castilla y león',
            'castile and león': 'castilla y león',
            'castille-la mancha': 'castilla-la mancha',
            'castile-la mancha': 'castilla-la mancha',
            'navarre': 'comunidad foral de navarra',
            'asturias': 'principado de asturias',
            'murcia': 'región de murcia',
            'madrid': 'comunidad de madrid',
        },
        'TH': {
            'lopburi': 'lop buri',
        },
        'CH': {
            'geneva': 'genève',
            'zurich': 'zürich',
            'bern': 'berne',
            'basel-city': 'basel-stadt',
            'basel city': 'basel-stadt',
            'saint gallen': 'sankt gallen',
            'st. gallen': 'sankt gallen',
            'grisons': 'graubünden',
        },
        'AT': {
            'upper austria': 'oberösterreich',
            'lower austria': 'niederösterreich',
            'vienna': 'wien',
            'styria': 'steiermark',
            'carinthia': 'kärnten',
            'tyrol': 'tirol',
        },
        'FI': {
            'uusimaa': 'southern finland',
            'southwest finland': 'western finland',
            'pirkanmaa': 'western finland',
            'varsinais-suomi': 'western finland',
            'satakunta': 'western finland',
            'central finland': 'western finland',
            'north ostrobothnia': 'oulu',
            'kainuu': 'oulu',
            'north karelia': 'eastern finland',
            'north savo': 'eastern finland',
            'south savo': 'eastern finland',
            'paijat-hame': 'southern finland',
            'päijät-häme': 'southern finland',
        },
        'DK': {
            'capital region': 'hovedstaden',
            'central denmark region': 'midtjylland',
            'central jutland': 'midtjylland',
            'north denmark region': 'nordjylland',
            'north denmark': 'nordjylland',
            'region zealand': 'sjælland',
            'zealand': 'sjælland',
            'region of southern denmark': 'syddanmark',
            'south denmark': 'syddanmark',
        },
        'RU': {
            'moscow oblast': 'moskva',
            'moscow': 'moskva',
            'mordoviya republic': 'mordovia',
            'st. petersburg': 'city of st. petersburg',
            'altai krai': 'altay',
            'altai': 'altay',
            'khanty-mansia': 'khanty-mansiy',
            'khakasiya republic': 'khakass',
            'kuzbass': 'kemerovo',
            'novgorod oblast': 'novgorod',
            'nizhny novgorod oblast': 'nizhegorod',
            'oryol oblast': 'orel',
        },
        'EG': {
            'giza': 'al jizah',
            'cairo': 'al qahirah',
            'alexandria': 'al iskandariyah',
            'dakahlia': 'ad daqahliyah',
            'damietta': 'dumyat',
            'monufia': 'al minufiyah',
            'sharqia': 'ash sharqiyah',
            'qalyubia': 'al qalyubiyah',
            'minya': 'al minya',
            'luxor': 'al uqsur',
            'assiut': 'asyut',
            'sohag': 'suhaj',
            'beni suweif': 'bani suwayf',
            'ismailia': 'al isma`iliyah',
            'gharbia': 'al gharbiyah',
            'kafr el-sheikh': 'kafr ash shaykh',
            'port said': 'bur sa`id',
            'red sea': 'al bahr al ahmar',
            'suez': 'as suways',
            'faiyum': 'al fayyum',
            'north sinai': 'shamal sina',
            'beheira': 'al buhayrah',
            'qena': 'qina',
        },
        'DZ': {
            'algiers': 'alger',
            'touggourt': 'ouargla',  # Touggourt is in Ouargla province
        },
        'PT': {
            'lisbon': 'lisboa',
        },
        'BE': {
            'brussels capital': 'bruxelles',
            'brussels': 'bruxelles',
            'flanders': 'vlaanderen',
            'wallonia': 'wallonie',
        },
        'MX': {
            'mexico city': 'distrito federal',
        },
        'IL': {
            'southern district': 'hadarom',
            'central district': 'hamerkaz',
            'northern district': 'hazafon',
        },
        'VN': {
            'ho chi minh': 'hồ chí minh',
            'ho chi minh city (hcmc)': 'hồ chí minh',
            'hanoi': 'hà nội',
            'da nang': 'đà nẵng',
            'da nang city': 'đà nẵng',
            'binh dinh': 'bình định',
            'quang tri': 'quảng trị',
            'đăk nông province': 'đắk nông',
            'dak nong': 'đắk nông',
            'dak lak': 'đắk lắk',
            'hai phong': 'hải phòng',
            'bac ninh': 'bắc ninh',
            'lam dong': 'lâm đồng',
            'phu tho': 'phú thọ',
            'dong nai': 'đồng nai',
            'can tho city': 'cần thơ',
            'can tho': 'cần thơ',
            'dong thap': 'đồng tháp',
            'vinh long': 'vĩnh long',
            'tra vinh': 'trà vinh',
            'quang ngai': 'quảng ngãi',
            'vn.48': 'đắk nông',
            'vn.08': 'tuyên quang',
            'vn.96': 'hồ chí minh',
            'tuyên quang province': 'tuyên quang',
        },
        'SA': {
            'mecca region': 'makkah',
            'riyadh region': 'ar riyad',
            'medina region': 'al madinah',
            'eastern province': 'ash-sharqīyah',
        },
        'RO': {
            'bucurești': 'bucharest',
            'bucharest': 'bucharest',
        },
        'IR': {
            'isfahan': 'esfahan',
            'east azerbaijan': 'east azarbaijan',
            'west azerbaijan': 'west azarbaijan',
            'māzandarān': 'mazandaran',
            'mazandaran': 'mazandaran',
            'chaharmahal and bakhtiari': 'chahar mahall and bakhtiari',
        },
        'KW': {
            'mubārak al kabīr': 'mubarak al-kabeer',
            'al aḩmadī': 'al ahmadi',
            'al ahmadi': 'al ahmadi',
            'al asimah': 'al kuwayt',
        },
        'BT': {
            'chukha': 'chhukha',
        },
        'CN': {
            'inner mongolia': 'nei mongol',
        },
        'HU': {
            'győr-moson-sopron': 'gyor-moson-sopron',
            'pest county': 'pest',
        },
        'FR': {
            'normandy': 'normandie',
            'brittany': 'bretagne',
            'rhône-alpes': 'auvergne-rhône-alpes',
            'rhone-alpes': 'auvergne-rhône-alpes',
            'rhone alpes': 'auvergne-rhône-alpes',
            'corsica': 'corse',
        },
        'PL': {
            'mazovia': 'mazowieckie',
            'greater poland': 'wielkopolskie',
            'silesia': 'śląskie',
            'subcarpathia': 'podkarpackie',
            'lesser poland': 'małopolskie',
            'pomerania': 'pomorskie',
            'west pomerania': 'zachodniopomorskie',
            'lower silesia': 'dolnośląskie',
            'warmia-masuria': 'warmińsko-mazurskie',
            'kuyavia-pomerania': 'kujawsko-pomorskie',
            'holy cross': 'świętokrzyskie',
            'lublin': 'lubelskie',
            'łódź voivodeship': 'łódzkie',
            'opole voivodeship': 'opolskie',
            'podlasie': 'podlaskie',
        },
        'AR': {
            'buenos aires f.d.': 'ciudad de buenos aires',
        },
        'UA': {
            'kyiv city': 'kiev city',
            'kyiv': 'kiev',
            'khmelnytskyi': "khmel'nyts'kyy",
            'vinnytsia': 'vinnytsya',
            'zaporizhzhia': 'zaporizhia',
            'mykolaiv': 'mykolayiv',
            'odesa': 'odessa',
        },
        'IQ': {
            'erbil': 'arbil',
            'duhok': 'dihok',
            'nineveh': 'ninawa',
            'bābil': 'babil',
            'kirkuk': "at-ta'mim",
            'karbalāʼ': "karbala'",
            'diyālá': 'diyala',
            'salah ad din': 'sala ad-din',
            'al qādisīyah': 'al-qadisiyah',
            'wāsiţ': 'wasit',
            'al muthanna governorate': 'al-muthannia',
            'anbar': 'al-anbar',
            'muthanna': 'al-muthannia',
        },
        'NO': {
            'vestland': 'hordaland',
            'viken': 'akershus',
            'innlandet': 'hedmark',
            'vestfold og telemark': 'vestfold',
            'agder': 'vest-agder',
            'troms og finnmark': 'troms',
            'trøndelag': 'sør-trøndelag',
            'østfold': 'Ãstfold',
        },
        'PH': {
            'metro manila': 'metropolitan manila',
            'national capital region': 'metropolitan manila',
            'ncr': 'metropolitan manila',
            'calabarzon': 'cavite',
            'central luzon': 'pampanga',
            'davao region': 'davao del sur',
            'central visayas': 'cebu',
            'northern mindanao': 'misamis oriental',
            'cordillera': 'benguet',
            'western visayas': 'iloilo',
            'eastern visayas': 'leyte',
            'zamboanga peninsula': 'zamboanga del sur',
            'caraga': 'agusan del norte',
            'mimaropa': 'oriental mindoro',
        },
        'IS': {
            'capital region': 'höfuðborgarsvæði',
            'greater reykjavik': 'höfuðborgarsvæði',
            'southern peninsula': 'suðurnes',
        },
        'GR': {
            'central macedonia': 'macedonia and thrace',
            'western macedonia': 'epirus and western macedonia',
            'east macedonia and thrace': 'macedonia and thrace',
            'epirus': 'epirus and western macedonia',
            'west greece': 'peloponnese, western greece and',
            'western greece': 'peloponnese, western greece and',
            'peloponnese': 'peloponnese, western greece and',
            'ionian islands': 'peloponnese, western greece and',
            'thessaly': 'thessaly and central greece',
            'central greece': 'thessaly and central greece',
        },
        'NP': {
            'bagmati province': 'central',
            'province 3': 'central',
            'gandaki province': 'west',
            'province 4': 'west',
            'lumbini province': 'west',
            'province 5': 'west',
            'koshi province': 'east',
            'koshi': 'east',
            'province 1': 'east',
            'madhesh province': 'central',
            'madhesh': 'central',
            'province 2': 'central',
            'karnali province': 'mid-western',
            'province 6': 'mid-western',
            'sudurpashchim province': 'far-western',
            'sudurpashchim pradesh': 'far-western',
            'province 7': 'far-western',
        },
        'RS': {
            'vojvodina': 'južno-bački',
            'central serbia': 'grad beograd',
            'belgrade': 'grad beograd',
        },
        'AL': {
            'tirana': 'tiranë',
        },
        'VE': {
            'distrito federal': 'distrito capital',
        },
        'ET': {
            'addis ababa': 'addis abeba',
            'oromiya': 'oromia',
            'sidama region': 'southern nations, nationalities',
            'south ethiopia regional state': 'southern nations, nationalities',
        },
        'LB': {
            'mont-liban': 'mount lebanon',
            'beyrouth': 'beirut',
            'béqaa': 'bekaa',
            'liban-nord': 'north',
        },
        'LK': {
            'western province': 'colombo',
            'central province': 'kandy',
            'southern province': 'galle',
            'northern province': 'jaffna',
            'eastern province': 'batticaloa',
        },
        'BH': {
            'manama': 'capital',
        },
        'QA': {
            'baladīyat ad dawḩah': 'ad dawhah',
            'doha': 'ad dawhah',
            'baladīyat ar rayyān': 'ar rayyan',
        },
        'BY': {
            'grodnenskaya': 'grodno',
            'minskaya': 'minsk',
            'minsk city': 'minsk',
            'brestskaya': 'brest',
            'gomelskaya': 'gomel',
            'mogilevskaya': 'mogilev',
            'vitebskaya': 'vitebsk',
        },
        'MT': {
            'ir-rabat': 'ċentrali',
            'valletta': 'nofsinhar',
            'dingli': 'ċentrali',
            "saint paul's bay": 'tramuntana',
            'il-fgura': 'xlokk',
        },
        'MY': {
            'penang': 'pulau pinang',
            'terengganu': 'trengganu',
        },
        'TM': {
            'ashgabat': 'ahal',
        },
        'LV': {
            'jūrmala': 'riga',
            'jurmala': 'riga',
            'ķekava': 'riga',
        },
        'KG': {
            'bishkek': 'chüy',
            'chuy region': 'chüy',
            'issyk-kul': 'ysyk-köl',
        },
        'NG': {
            'fct': 'federal capital territory',
        },
        'KZ': {
            'mangghystaū': 'mangghystau',
            'mangystau': 'mangghystau',
            'astana': 'aqmola',
            'almaty city': 'almaty',
            'almaty region': 'almaty',
            "aktyubinskaya oblast'": 'aqtöbe',
            'aktyubinskaya oblast': 'aqtöbe',
            'aktobe': 'aqtöbe',
            'shymkent': 'south kazakhstan',
            'karaganda': 'qaraghandy',
            'batys qazaqstan': 'west kazakhstan',
            'jetisu region': 'almaty',
        },
        'CL': {
            'biobío': 'bío-bío',
            'biobio': 'bío-bío',
            "o'higgins region": "libertador general bernardo o'hi",
        },
        'SK': {
            'bratislava region': 'bratislavský',
            'bratislava': 'bratislavský',
            'kosice region': 'košický',
            'trenčín region': 'trenčiansky',
            'trencin region': 'trenčiansky',
            'prešov region': 'prešovský',
            'presov region': 'prešovský',
            'nitra region': 'nitriansky',
            'trnava region': 'trnavský',
            'žilina region': 'žilinský',
            'zilina region': 'žilinský',
            'banská bystrica region': 'banskobystrický',
            'banska bystrica region': 'banskobystrický',
        },
        'BN': {
            'brunei-muara district': 'brunei and muara',
        },
        'TW': {
            'takao': 'kaohsiung',
        },
        'HR': {
            'county of osijek-baranja': 'osjecko-baranjska',
            'osijek-baranja': 'osjecko-baranjska',
            'međimurje': 'medimurska',
            'brod-posavina': 'brodsko-posavska',
            'primorje-gorski kotar': 'primorsko-goranska',
            'split-dalmatia': 'splitsko-dalmatinska',
        },
        'BA': {
            'federation of b&h': 'federacija bosna i hercegovina',
            'federation of bosnia and herzegovina': 'federacija bosna i hercegovina',
            'republika srpska': 'repuplika srpska',
        },
        'BR': {
            'federal district': 'distrito federal',
        },
        'OM': {
            'northeastern governorate': 'ash sharqiyah north',
            'ad dhahirah': 'al dhahira',
        },
        'SI': {
            'ljubljana': 'osrednjeslovenska',
            'bled': 'gorenjska',
            'velenje': 'savinjska',
            'maribor city municipality': 'podravska',
            'kranj': 'gorenjska',
        },
        'UG': {
            'central region': 'kampala',
            'western region': 'kabarole',
            'eastern region': 'jinja',
            'northern region': 'gulu',
        },
        'GE': {
            'adjara': 'ajaria',
            'samegrelo and zemo svaneti': 'samegrelo-zemo svaneti',
        },
        'MG': {
            'analamanga': 'antananarivo',
            'atsinanana': 'toamasina',
        },
        'LY': {
            'banghāzī': 'benghazi',
        },
        'JO': {
            'jerash': 'jarash',
            'ajloun': 'ajlun',
        },
        'YE': {
            "ta'izz": "ta`izz",
            'amanat alasimah': 'amanat al asimah',
        },
        'DO': {
            'hermanas mirabal': 'salcedo',
        },
        'HN': {
            'bay islands': 'islas de la bahía',
        },
        'PE': {
            'lima region': 'lima',
            'cuzco department': 'cusco',
        },
        'NI': {
            'south caribbean coast': 'atlántico sur',
        },
        'TL': {
            'dili municipality': 'dili',
        },
        'LA': {
            'bolikhamsai': 'bolikhamxai',
        },
        'MR': {
            'mauritania': 'nouakchott',
        },
        'AZ': {
            'baki': 'absheron',
            'baku': 'absheron',
            'yevlax city': 'aran',
            'gǝncǝ': 'ganja-qazakh',
            'ganja': 'ganja-qazakh',
            'sumqayit': 'absheron',
            'nakhichevan assr': 'nakhchivan',
            'barda': 'aran',
            'abşeron': 'absheron',
            'mingǝcevir': 'aran',
        },
        'MD': {
            'chișinău municipality': 'chișinău',
            'chisinau': 'chișinău',
            'gagauzia': 'gagauzia',
        },
        'IE': {
            'leinster': 'dublin',
            'munster': 'cork city',
            'connacht': 'galway',
            'ulster': 'donegal',
        },
        'KE': {
            'tharaka - nithi': 'tharaka-nithi',
        },
        'PK': {
            'gilgit-baltistan': 'federally administered tribal ar',
            'azad kashmir': 'federally administered tribal ar',
        },
        'TR': {
            'kahramanmaraş': 'k. maras',
            'kahramanmaras': 'k. maras',
            'izmir province': 'izmir',
            'İzmir province': 'izmir',
            'i̇zmir province': 'izmir',
            'eskişehir': 'eskisehir',
        },
        'CZ': {
            'central bohemia': 'středočeský',
            'south moravian': 'jihomoravský',
        },
        'UZ': {
            'tashkent': 'toshkent shahri',
            'samarkand': "samarqand'",
            'bukhara': 'buxoro',
            'andijan region': 'andijon',
        },
        'CU': {
            'havana': 'ciudad de la habana',
            'la habana': 'ciudad de la habana',
        },
        'MA': {
            'souss-massa': 'souss - massa - draâ',
            'casablanca-settat': 'grand casablanca',
            'rabat-salé-kénitra': 'rabat - salé - zemmour - zaer',
            'fès-meknès': 'fès - boulemane',
            'marrakech-safi': 'marrakech - tensift - al haouz',
            'marrakesh-safi': 'marrakech - tensift - al haouz',
            'tanger-tétouan-al hoceïma': 'tanger - tétouan',
            'tanger-tetouan-al hoceima': 'tanger - tétouan',
            'béni mellal-khénifra': 'tadla - azilal',
            'beni mellal-khenifra': 'tadla - azilal',
        },
        'JM': {
            'st. elizabeth': 'saint elizabeth',
        },
        'GP': {
            'guadeloupe': 'basse-terre',
        },
        'RE': {
            'réunion': 'saint-denis',
        },
        'VG': {
            'british virgin islands': 'tortola',
        },
        'LU': {
            'esch-sur-alzette': 'luxembourg',
        },
        'SY': {
            'latakia': 'lattakia',
        },
        'ID': {
            'east java': 'jawa timur',
            'west java': 'jawa barat',
            'central java': 'jawa tengah',
            'south sumatra': 'sumatera selatan',
            'north sumatra': 'sumatera utara',
            'west sumatra': 'sumatera barat',
            'west kalimantan': 'kalimantan barat',
            'east kalimantan': 'kalimantan timur',
            'south kalimantan': 'kalimantan selatan',
            'central kalimantan': 'kalimantan tengah',
            'north kalimantan': 'kalimantan utara',
            'south sulawesi': 'sulawesi selatan',
            'central sulawesi': 'sulawesi tengah',
            'north sulawesi': 'sulawesi utara',
            'west nusa tenggara': 'nusa tenggara barat',
            'riau islands': 'kepulauan riau',
            'central papua': 'papua',
            'southwest papua': 'papua barat',
            'bangka–belitung islands': 'bangka belitung',
            'east nusa tenggara': 'nusa tenggara timur',
        },
        'CI': {
            'abidjan autonomous district': 'abidjan',
            'vallée du bandama district': 'vallée du bandama',
            'lacs district': 'lacs',
        },
        'PA': {
            'panamá oeste province': 'panamá',
        },
        'MV': {
            'kaafu atoll': 'kaafu',
        },
        'CO': {
            'cauca department': 'cauca',
        },
        'LT': {
            'vilnius': 'vilniaus',
            'kaunas': 'kauno',
            'klaipeda': 'klaipedos',
            'klaipėda county': 'klaipedos',
            'panevezys': 'panevezio',
            'panevėžys': 'panevezio',
            'siauliai': 'šiauliai',
        },
    }

    # Create name normalization function for better matching
    def normalize_name(name: str) -> str:
        """Normalize subdivision name for matching."""
        if not name:
            return ""
        # Convert to lowercase
        name = name.lower()
        # Remove common prefixes/suffixes
        prefixes = ["state of ", "province of ", "region of ", "republic of "]
        for prefix in prefixes:
            if name.startswith(prefix):
                name = name[len(prefix):]
        # Replace accented characters with ASCII equivalents
        replacements = {
            'á': 'a', 'à': 'a', 'â': 'a', 'ä': 'a', 'ã': 'a', 'ą': 'a', 'ă': 'a', 'ā': 'a',
            'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e', 'ę': 'e', 'ě': 'e', 'ė': 'e', 'ǝ': 'e',
            'í': 'i', 'ì': 'i', 'î': 'i', 'ï': 'i', 'ı': 'i', 'ī': 'i',
            'ó': 'o', 'ò': 'o', 'ô': 'o', 'ö': 'o', 'õ': 'o', 'ő': 'o', 'ō': 'o',
            'ú': 'u', 'ù': 'u', 'û': 'u', 'ü': 'u', 'ű': 'u', 'ū': 'u',
            'ñ': 'n', 'ń': 'n', 'ň': 'n',
            'ç': 'c', 'ć': 'c', 'č': 'c', 'ċ': 'c',
            'ß': 'ss', 'ş': 's', 'ș': 's', 'š': 's', 'ś': 's',
            'ø': 'o', 'å': 'a', 'æ': 'ae',
            'ł': 'l', 'ľ': 'l',
            'ý': 'y', 'ÿ': 'y',
            'ž': 'z', 'ź': 'z', 'ż': 'z',
            'ř': 'r', 'ŕ': 'r',
            'ţ': 't', 'ț': 't', 'ť': 't',
            'đ': 'd', 'ď': 'd',
            'ğ': 'g',
            'ħ': 'h', 'ḥ': 'h',
            '-': ' ', '_': ' ', "'": '', '\u2019': '', '\u2018': '', '\u02bc': '',
        }
        for old, new in replacements.items():
            name = name.replace(old, new)
        return name.strip()
    
    def get_aliased_name(country_code: str, name: str) -> str:
        """Get the GADM name for a region using alias lookup."""
        if country_code in name_aliases:
            name_lower = name.lower()
            # Try exact match first
            if name_lower in name_aliases[country_code]:
                return name_aliases[country_code][name_lower]
            # Try normalized match
            name_norm = normalize_name(name)
            for alias_key, alias_val in name_aliases[country_code].items():
                if normalize_name(alias_key) == name_norm:
                    return alias_val
        return name

    # Build normalized lookup for our data (including aliases)
    normalized_subdivision_data = {}
    aliased_subdivision_data = {}
    for key, bytes_val in subdivision_data.items():
        parts = key.split("/", 1)
        if len(parts) == 2:
            country_code = parts[0]
            orig_name = parts[1]
            
            # Add normalized version
            norm_name = normalize_name(orig_name)
            norm_key = f"{country_code}/{norm_name}"
            normalized_subdivision_data[norm_key] = normalized_subdivision_data.get(norm_key, 0) + bytes_val
            
            # Add aliased version (normalized)
            aliased_name = get_aliased_name(country_code, orig_name)
            if aliased_name != orig_name:
                aliased_norm = normalize_name(aliased_name)
                aliased_key = f"{country_code}/{aliased_norm}"
                aliased_subdivision_data[aliased_key] = aliased_subdivision_data.get(aliased_key, 0) + bytes_val

    # Track which data keys have been matched
    matched_data_keys = set()
    
    # Create a lookup for each subdivision
    world_admin1['bytes_downloaded'] = 0
    matched_count = 0
    
    for idx, row in world_admin1.iterrows():
        country_iso3 = row['GID_0']  # 3-letter ISO code
        subdivision_name = row['NAME_1']  # GADM subdivision name
        
        # Skip if no subdivision name
        if not subdivision_name:
            continue
        
        # Find 2-letter country code
        country_code = None
        for iso2, iso3 in iso2_to_iso3.items():
            if iso3 == country_iso3:
                country_code = iso2
                break
        
        if country_code:
            total_bytes = 0
            matched_any = False
            norm_subdiv = normalize_name(subdivision_name)
            norm_key = f"{country_code}/{norm_subdiv}"
            
            # Try exact match with subdivision name
            key = f"{country_code}/{subdivision_name}"
            if key in subdivision_data:
                total_bytes += subdivision_data[key]
                matched_data_keys.add(key)
                matched_any = True
            
            # Try normalized match (add all keys that normalize to this)
            if norm_key in normalized_subdivision_data:
                for orig_key in subdivision_data.keys():
                    parts = orig_key.split("/", 1)
                    if len(parts) == 2 and parts[0] == country_code:
                        if normalize_name(parts[1]) == norm_subdiv and orig_key not in matched_data_keys:
                            total_bytes += subdivision_data[orig_key]
                            matched_data_keys.add(orig_key)
                            matched_any = True
            
            # Try aliased match (add all keys that alias to this)
            if norm_key in aliased_subdivision_data:
                for orig_key in subdivision_data.keys():
                    parts = orig_key.split("/", 1)
                    if len(parts) == 2 and parts[0] == country_code:
                        aliased = get_aliased_name(country_code, parts[1])
                        if normalize_name(aliased) == norm_subdiv and orig_key not in matched_data_keys:
                            total_bytes += subdivision_data[orig_key]
                            matched_data_keys.add(orig_key)
                            matched_any = True
            
            # Try partial match as last resort
            if not matched_any:
                for sub_key, bytes_val in subdivision_data.items():
                    if sub_key.startswith(f"{country_code}/") and sub_key not in matched_data_keys:
                        sub_name = sub_key.split("/", 1)[1]
                        norm_sub = normalize_name(sub_name)
                        if (norm_sub in norm_subdiv or norm_subdiv in norm_sub) and len(norm_sub) > 3:
                            total_bytes += bytes_val
                            matched_data_keys.add(sub_key)
                            matched_any = True
                            break
            
            if matched_any:
                world_admin1.at[idx, 'bytes_downloaded'] = total_bytes
                matched_count += 1

    print(f"Matched {matched_count} subdivisions with download data")

    # Report unmatched subdivisions
    unmatched = set(subdivision_data.keys()) - matched_data_keys
    if unmatched:
        print(f"\nUnmatched regions ({len(unmatched)}):")
        # Sort by bytes downloaded to show most important unmatched first
        unmatched_sorted = sorted(unmatched, key=lambda k: subdivision_data[k], reverse=True)
        for key in unmatched_sorted:
            print(f"  {key}: {format_bytes(subdivision_data[key])}")
    
    # Calculate total matched vs unmatched bytes
    matched_bytes = sum(subdivision_data[k] for k in matched_data_keys if k in subdivision_data)
    unmatched_bytes = sum(subdivision_data[k] for k in unmatched)
    total_bytes = matched_bytes + unmatched_bytes
    if total_bytes > 0:
        match_pct = 100 * matched_bytes / total_bytes
        print(f"\nMatching coverage: {format_bytes(matched_bytes)} / {format_bytes(total_bytes)} ({match_pct:.1f}%)")
    
    # If dry run, skip plotting
    if dry_run:
        print("\n[Dry run - skipping plot generation]")
        return

    # Create figure
    fig, ax = plt.subplots(figsize=(20, 12), facecolor='white')
    ax.set_facecolor('white')

    # Determine max bytes for visualization (use provided max or data max)
    data_max = world_admin1['bytes_downloaded'].max()
    if max_bytes is not None:
        MAX_BYTES_FOR_VIS = max_bytes
        print(f"Using max cap: {format_bytes(MAX_BYTES_FOR_VIS)}")
        world_admin1['bytes_downloaded_capped'] = world_admin1['bytes_downloaded'].clip(upper=MAX_BYTES_FOR_VIS)
    else:
        MAX_BYTES_FOR_VIS = data_max
        world_admin1['bytes_downloaded_capped'] = world_admin1['bytes_downloaded']

    # Apply log transformation if requested (using capped values for visualization)
    if log_scale:
        world_admin1['plot_value'] = world_admin1['bytes_downloaded_capped'].apply(
            lambda x: np.log10(x + 1) if x > 0 else 0
        )
        scale_label = "Log₁₀(Bytes Downloaded + 1)"
    else:
        world_admin1['plot_value'] = world_admin1['bytes_downloaded_capped']
        scale_label = "Bytes Downloaded"

    # Get subdivisions with data (after adding plot_value column)
    subdivisions_with_data = world_admin1[world_admin1['bytes_downloaded'] > 0].copy()
    print(f"Subdivisions with data: {len(subdivisions_with_data)}")

    # Set up color normalization
    values_with_data = subdivisions_with_data['plot_value']
    if len(values_with_data) > 0:
        vmin = values_with_data.min()
        if log_scale:
            vmax = np.log10(MAX_BYTES_FOR_VIS + 1)
        else:
            vmax = MAX_BYTES_FOR_VIS
    else:
        vmin, vmax = 0, 1

    norm = Normalize(vmin=vmin, vmax=vmax)
    cmap = plt.cm.YlOrRd

    # Plot subdivisions without data in light gray
    no_data = world_admin1[world_admin1['bytes_downloaded'] == 0]
    no_data.plot(
        ax=ax,
        color='lightgray',
        edgecolor='white',
        linewidth=0.1,
        alpha=0.5
    )

    # Plot subdivisions with data using colormap
    if len(subdivisions_with_data) > 0:
        subdivisions_with_data.plot(
            ax=ax,
            column='plot_value',
            cmap=cmap,
            norm=norm,
            edgecolor='white',
            linewidth=0.1,
            alpha=0.8
        )

    # Add subdivision boundaries
    world_admin1.boundary.plot(
        ax=ax,
        linewidth=0.15,
        color='#333333',
        alpha=0.2
    )

    # Set extent to exclude Antarctica
    ax.set_xlim(-180, 180)
    ax.set_ylim(-60, 85)

    # Remove axis elements
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    # Add colorbar if we have data
    if len(subdivisions_with_data) > 0:
        if vertical_colorbar:
            cbar_ax = fig.add_axes([1.0, 0.35, 0.015, 0.3])
            orientation = 'vertical'
        else:
            cbar_ax = fig.add_axes([0.375, 0.08, 0.25, 0.02])
            orientation = 'horizontal'
        sm = ScalarMappable(norm=norm, cmap=cmap)
        sm.set_array([])
        cbar = fig.colorbar(sm, cax=cbar_ax, orientation=orientation)
        if vertical_colorbar:
            cbar.ax.tick_params(
                labelsize=14, left=False, right=True, labelleft=False, labelright=True
            )
        else:
            cbar.ax.tick_params(
                labelsize=14, bottom=True, top=False, labelbottom=True, labeltop=False
            )

        # Define fixed tick values for readable labels
        unit_values = [1024, 1024**2, 1024**3, 1024**4, 1024**5]
        unit_labels = ["1 KB", "1 MB", "1 GB", "1 TB", "1 PB"]


        min_val = subdivisions_with_data['bytes_downloaded'].min()
        # Use capped max for colorbar ticks
        max_val_for_ticks = MAX_BYTES_FOR_VIS

        if log_scale:
            min_log = np.log10(min_val + 1)
            max_log = np.log10(max_val_for_ticks + 1)
            valid_ticks = []
            valid_labels = []
            for value, label in zip(unit_values, unit_labels):
                log_val = np.log10(value + 1)
                if min_log <= log_val < max_log:  # Use < instead of <= to leave room for cap label
                    valid_ticks.append(log_val)
                    valid_labels.append(label)

            # Add "≥ [max]" label at the top if a cap is set
            if max_bytes is not None:
                valid_ticks.append(max_log)
                valid_labels.append(f"≥ {format_bytes(max_bytes)}")

            if valid_ticks:
                cbar.set_ticks(valid_ticks)
                cbar.set_ticklabels(valid_labels)

        cbar.set_label("Data Downloaded", labelpad=10, fontsize=20)

    plt.tight_layout()

    # Save outputs as PNG (high resolution)
    png_file = output_file.replace('.svg', '.png')
    plt.savefig(png_file, dpi=300, bbox_inches='tight', facecolor='white', format='png')
    print(f"\nChoropleth map saved as: {png_file}")

    # Print summary statistics
    print(f"\nSummary Statistics:")
    print(f"Total subdivisions: {len(world_admin1)}")
    print(f"Subdivisions with data: {len(subdivisions_with_data)}")
    if len(subdivisions_with_data) > 0:
        total_bytes = subdivisions_with_data['bytes_downloaded'].sum()
        print(f"Total data downloaded: {format_bytes(total_bytes)}")
        print(f"\nTop 10 subdivisions by download volume:")
        top_subdivisions = subdivisions_with_data.nlargest(10, 'bytes_downloaded')
        for _, row in top_subdivisions.iterrows():
            print(f"  {row['COUNTRY']} / {row['NAME_1']}: {format_bytes(row['bytes_downloaded'])}")

    plt.close()


def get_nwb_dandiset_ids(data_path: str = "../access-summaries/content") -> List[str]:
    """
    Get list of dandiset IDs that contain NWB data, using DANDI API metadata.

    Results are cached to data/nwb_dandiset_ids.json with 24-hour expiry.

    Parameters
    ----------
    data_path : str
        Path to access summaries directory, used to determine which dandisets to check.

    Returns
    -------
    list of str
        Dandiset IDs that contain NWB files.
    """
    import time

    cache_path = Path("data/nwb_dandiset_ids.json")
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    # Check cache (24h expiry)
    if cache_path.exists():
        cache_data = json.loads(cache_path.read_text())
        if time.time() - cache_data.get("timestamp", 0) < 86400:
            print(f"Using cached NWB dandiset list ({len(cache_data['ids'])} dandisets)")
            return cache_data["ids"]

    # Get all dandiset IDs from summaries directory
    summaries_dir = Path(data_path) / "summaries"
    all_ids = sorted(
        d.name for d in summaries_dir.iterdir()
        if d.is_dir() and d.name.isdigit()
    )

    print(f"Querying DANDI API to find NWB dandisets ({len(all_ids)} to check)...")

    from dandi.dandiapi import DandiAPIClient

    nwb_ids = []
    client = DandiAPIClient()
    for dandiset_id in tqdm(all_ids, desc="Checking dandisets"):
        try:
            dandiset = client.get_dandiset(dandiset_id)
            raw_metadata = dandiset.get_raw_metadata()
            standards = raw_metadata.get("assetsSummary", {}).get("dataStandard", [])
            if any("NWB" in s.get("name", "").upper() for s in standards):
                nwb_ids.append(dandiset_id)
        except Exception:
            continue

    print(f"Found {len(nwb_ids)} NWB dandisets out of {len(all_ids)} total")

    # Save cache
    cache_path.write_text(json.dumps({"timestamp": time.time(), "ids": nwb_ids}))

    return nwb_ids


def main() -> None:
    """
    Main function to parse arguments and create subdivision choropleth.

    Examples
    --------
    >>> # Run from command line
    >>> # python create_subdivision_choropleth.py --dandiset 000026 --log-scale
    """
    parser = argparse.ArgumentParser(
        description="Create static choropleth map of DANDI downloads by subdivision (uses GADM data)"
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
        default="output/subdivision_choropleth.svg",
        help="Output file name (default: output/subdivision_choropleth.svg)",
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Test matching logic without generating plot (for faster iteration)",
    )
    parser.add_argument(
        "--max",
        "-m",
        default=None,
        help="Maximum value for color scale (e.g., '10TB', '500GB'). Values above this are capped. Default: use data max.",
    )
    parser.add_argument(
        "--nwb-only",
        action="store_true",
        help="Only include dandisets that contain NWB data",
    )
    parser.add_argument(
        "--vertical-colorbar",
        action="store_true",
        help="Place colorbar vertically on the right side instead of horizontally at the bottom",
    )

    args = parser.parse_args()

    # Parse max bytes if provided
    max_bytes = None
    if args.max:
        try:
            max_bytes = parse_bytes_string(args.max)
        except ValueError as e:
            print(f"Error parsing --max value: {e}")
            return

    # Parse comma-separated dandisets
    dandiset_ids = None
    if args.dandiset:
        dandiset_ids = [d.strip() for d in args.dandiset.split(",") if d.strip()]

    # Filter to NWB-only dandisets if requested
    if args.nwb_only:
        nwb_ids = get_nwb_dandiset_ids(args.data_path)
        if dandiset_ids:
            dandiset_ids = [d for d in dandiset_ids if d in set(nwb_ids)]
            print(f"After NWB filter: {len(dandiset_ids)} dandisets")
        else:
            dandiset_ids = nwb_ids

    # Update output filename if specific dandisets
    if args.nwb_only and args.output == "output/subdivision_choropleth.svg":
        args.output = args.output.replace(".svg", "_nwb_only.svg")
    elif dandiset_ids and not args.nwb_only and args.output == "output/subdivision_choropleth.svg":
        base_name = args.output.replace(".svg", "")
        if len(dandiset_ids) == 1:
            args.output = f"{base_name}_{dandiset_ids[0]}.svg"
        else:
            dandiset_str = "_".join(dandiset_ids)
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

    if args.dry_run:
        print("Running matching test (dry run)...")
    else:
        print("Creating subdivision choropleth map...")
    create_subdivision_choropleth(
        region_data,
        log_scale=args.log_scale,
        output_file=args.output,
        dandiset_ids=dandiset_ids,
        dry_run=args.dry_run,
        max_bytes=max_bytes,
        vertical_colorbar=args.vertical_colorbar,
    )


if __name__ == "__main__":
    main()
