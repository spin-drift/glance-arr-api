import os
import requests
from datetime import datetime, timedelta
from flask import Flask, jsonify

# --- Configuration ---
SONARR_URL = os.getenv('SONARR_URL')
SONARR_API_KEY = os.getenv('SONARR_API_KEY')
RADARR_URL = os.getenv('RADARR_URL')
RADARR_API_KEY = os.getenv('RADARR_API_KEY')
SONARR_DAYS_AHEAD = int(os.getenv('SONARR_DAYS_AHEAD', 90))
RADARR_DAYS_AHEAD = int(os.getenv('RADARR_DAYS_AHEAD', 365))


app = Flask(__name__)

def normalize_sonarr_item(item):
    series_info = item.get('series', {})
    title = series_info.get('title', 'Unknown Show')
    return {
        "release_datetime": item.get('airDateUtc'),
        "title": title,
        "type": "show",
        "has_file": item.get('hasFile', False),
        "details": f"S{item.get('seasonNumber'):02d}E{item.get('episodeNumber'):02d}"
    }

def normalize_radarr_item(item):
    release_type = "In Cinemas"
    release_date = item.get('inCinemas')
    if item.get('digitalRelease'):
        release_date = item.get('digitalRelease')
        release_type = "Digital Release"
    return {
        "release_datetime": release_date,
        "title": item.get('title'),
        "type": "movie",
        "has_file": item.get('hasFile', False),
        "details": release_type
    }

def calculate_sonarr_stats(series_data):
    """Calculate Sonarr statistics from series data"""
    total_series = len(series_data)
    series_ended = 0
    series_continuing = 0
    monitored_series = 0
    unmonitored_series = 0
    total_episodes = 0
    episodes_with_files = 0
    total_size = 0
    
    for series in series_data:
        # Series status
        if series.get('ended', False) or series.get('status') == 'ended':
            series_ended += 1
        elif series.get('status') == 'continuing':
            series_continuing += 1
            
        # Monitoring status
        if series.get('monitored', False):
            monitored_series += 1
        else:
            unmonitored_series += 1
            
        # Episode statistics
        stats = series.get('statistics', {})
        total_episodes += stats.get('totalEpisodeCount', 0)
        episodes_with_files += stats.get('episodeFileCount', 0)
        total_size += stats.get('sizeOnDisk', 0)
    
    # Convert size to TiB
    total_size_tib = total_size / (1024**4) if total_size > 0 else 0
    
    return {
        "series": total_series,
        "ended": series_ended,
        "continuing": series_continuing,
        "monitored": monitored_series,
        "unmonitored": unmonitored_series,
        "episodes": total_episodes,
        "files": episodes_with_files,
        "total_file_size": f"{total_size_tib:.1f} TiB"
    }

def calculate_radarr_stats(movies_data):
    """Calculate Radarr statistics from movies data"""
    total_movies = len(movies_data)
    movies_with_files = 0
    monitored_movies = 0
    unmonitored_movies = 0
    total_size = 0
    
    for movie in movies_data:
        # File status
        if movie.get('hasFile', False):
            movies_with_files += 1
            
        # Monitoring status
        if movie.get('monitored', False):
            monitored_movies += 1
        else:
            unmonitored_movies += 1
            
        # Size calculation
        total_size += movie.get('sizeOnDisk', 0)
    
    # Convert size to TiB
    total_size_tib = total_size / (1024**4) if total_size > 0 else 0
    
    return {
        "movies": total_movies,
        "movie_files": movies_with_files,
        "monitored": monitored_movies,
        "unmonitored": unmonitored_movies,
        "total_file_size": f"{total_size_tib:.1f} TiB"
    }

@app.route('/api/agenda')
def get_agenda():
    all_items = []
    
    start_date = datetime.utcnow().strftime('%Y-%m-%d')
    sonarr_end_date = (datetime.utcnow() + timedelta(days=SONARR_DAYS_AHEAD)).strftime('%Y-%m-%d')
    radarr_end_date = (datetime.utcnow() + timedelta(days=RADARR_DAYS_AHEAD)).strftime('%Y-%m-%d')
    
    # Fetch data from Sonarr
    try:
        sonarr_endpoint = f"{SONARR_URL}/api/v3/calendar?start={start_date}&end={sonarr_end_date}&includeSeries=true"
        headers = {'X-Api-Key': SONARR_API_KEY}
        response = requests.get(sonarr_endpoint, headers=headers, timeout=10)
        response.raise_for_status()
        sonarr_data = response.json()
        for item in sonarr_data:
            all_items.append(normalize_sonarr_item(item))
    except requests.exceptions.RequestException as e:
        print(f"Error fetching from Sonarr: {e}")

    # Fetch data from Radarr
    try:
        radarr_endpoint = f"{RADARR_URL}/api/v3/calendar?start={start_date}&end={radarr_end_date}"
        headers = {'X-Api-Key': RADARR_API_KEY}
        response = requests.get(radarr_endpoint, headers=headers, timeout=10)
        response.raise_for_status()
        radarr_data = response.json() 
        for item in radarr_data:
            normalized_item = normalize_radarr_item(item)
            if normalized_item.get('release_datetime') and normalized_item['release_datetime'][:10] >= start_date:
                all_items.append(normalized_item)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching from Radarr: {e}")

    # Sort all collected items by their release datetime
    all_items.sort(key=lambda x: x.get('release_datetime'))

    # Group the sorted items by date
    grouped_agenda = {}
    for item in all_items:
        if item.get('release_datetime'):
            date_key = item['release_datetime'][:10]
            if date_key not in grouped_agenda:
                grouped_agenda[date_key] = []
            grouped_agenda[date_key].append(item)
    
    agenda_list = []
    for date, items in grouped_agenda.items():
        agenda_list.append({
            "date": date,
            "items": items
        })

    return jsonify(agenda_list)

@app.route('/api/stats')
def get_stats():
    """Get combined statistics from both Sonarr and Radarr"""
    stats = {
        "sonarr": {},
        "radarr": {},
        "error": None
    }
    
    # Fetch Sonarr series data
    try:
        sonarr_endpoint = f"{SONARR_URL}/api/v3/series"
        headers = {'X-Api-Key': SONARR_API_KEY}
        response = requests.get(sonarr_endpoint, headers=headers, timeout=10)
        response.raise_for_status()
        sonarr_data = response.json()
        stats["sonarr"] = calculate_sonarr_stats(sonarr_data)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching Sonarr stats: {e}")
        stats["error"] = f"Sonarr error: {str(e)}"
        stats["sonarr"] = {
            "series": 0,
            "ended": 0,
            "continuing": 0,
            "monitored": 0,
            "unmonitored": 0,
            "episodes": 0,
            "files": 0,
            "total_file_size": "0.0 TiB"
        }
    
    # Fetch Radarr movies data
    try:
        radarr_endpoint = f"{RADARR_URL}/api/v3/movie"
        headers = {'X-Api-Key': RADARR_API_KEY}
        response = requests.get(radarr_endpoint, headers=headers, timeout=10)
        response.raise_for_status()
        radarr_data = response.json()
        stats["radarr"] = calculate_radarr_stats(radarr_data)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching Radarr stats: {e}")
        if stats["error"]:
            stats["error"] += f" | Radarr error: {str(e)}"
        else:
            stats["error"] = f"Radarr error: {str(e)}"
        stats["radarr"] = {
            "movies": 0,
            "movie_files": 0,
            "monitored": 0,
            "unmonitored": 0,
            "total_file_size": "0.0 TiB"
        }
    
    return jsonify(stats)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)
