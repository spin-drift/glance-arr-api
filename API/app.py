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
    release_type = "Cinema"
    release_date = item.get('inCinemas')
    if item.get('digitalRelease'):
        release_date = item.get('digitalRelease')
        release_type = "Digital"
    return {
        "release_datetime": release_date,
        "title": item.get('title'),
        "type": "movie",
        "has_file": item.get('hasFile', False),
        "details": release_type
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)