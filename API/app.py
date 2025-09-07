import os
import requests
from datetime import datetime, timedelta
from flask import Flask, jsonify, request

# --- Configuration ---
SONARR_URL = os.getenv("SONARR_URL")
SONARR_API_KEY = os.getenv("SONARR_API_KEY")
RADARR_URL = os.getenv("RADARR_URL")
RADARR_API_KEY = os.getenv("RADARR_API_KEY")
SONARR_DAYS_AHEAD = int(os.getenv("SONARR_DAYS_AHEAD", 90))
RADARR_DAYS_AHEAD = int(os.getenv("RADARR_DAYS_AHEAD", 365))

app = Flask(__name__)


def normalize_sonarr_item(item):
    """
    Normalize a Sonarr calendar item to a standard dictionary format.

    Args:
        item (dict): Raw Sonarr calendar item.

    Returns:
        dict: Normalized item with release date, title, type, file status, and episode details.
    """
    series_info = item.get("series", {})
    title = series_info.get("title", "Unknown Show")
    return {
        "release_datetime": item.get("airDateUtc"),
        "title": title,
        "type": "show",
        "has_file": item.get("hasFile", False),
        "details": f"S{item.get('seasonNumber'):02d}E{item.get('episodeNumber'):02d}",
    }


def normalize_radarr_item(item):
    """
    Normalize a Radarr calendar item to a standard dictionary format.

    Args:
        item (dict): Raw Radarr calendar item.

    Returns:
        dict: Normalized item with release date, title, type, file status, and release details.
    """
    release_type = "In Cinemas"
    release_date = item.get("inCinemas")
    if item.get("digitalRelease"):
        release_date = item.get("digitalRelease")
        release_type = "Digital Release"
    return {
        "release_datetime": release_date,
        "title": item.get("title"),
        "type": "movie",
        "has_file": item.get("hasFile", False),
        "details": release_type,
    }


def format_ordered_stats(stats, fields_param):
    """
    Format statistics according to a custom field order specification.

    Args:
        stats (dict): Statistics data for Sonarr and Radarr.
        fields_param (str): Comma-separated field order and optional custom labels.

    Returns:
        dict: Ordered statistics fields and any error messages.
    """
    ordered_data = []

    # Check if commas formatting is requested
    use_commas = request.args.get("commas", "").lower() in ["true", "1", "yes"]

    def format_value(value):
        if (
            use_commas
            and isinstance(value, (int, float))
            and not isinstance(value, str)
        ):
            return f"{value:,}"
        return value

    field_map = {
        "sonarr_header": {"value": "TV", "type": "header"},
        "sonarr_series": {
            "value": format_value(stats["sonarr"]["series"]),
            "field": "sonarr.series",
        },
        "sonarr_ended": {
            "value": format_value(stats["sonarr"]["ended"]),
            "field": "sonarr.ended",
        },
        "sonarr_continuing": {
            "value": format_value(stats["sonarr"]["continuing"]),
            "field": "sonarr.continuing",
        },
        "sonarr_monitored": {
            "value": format_value(stats["sonarr"]["monitored"]),
            "field": "sonarr.monitored",
        },
        "sonarr_unmonitored": {
            "value": format_value(stats["sonarr"]["unmonitored"]),
            "field": "sonarr.unmonitored",
        },
        "sonarr_episodes": {
            "value": format_value(stats["sonarr"]["episodes"]),
            "field": "sonarr.episodes",
        },
        "sonarr_files": {
            "value": format_value(stats["sonarr"]["files"]),
            "field": "sonarr.files",
        },
        "sonarr_size": {
            "value": stats["sonarr"]["size"],
            "field": "sonarr.size",
        },
        "radarr_header": {"value": "Movies", "type": "header"},
        "radarr_movies": {
            "value": format_value(stats["radarr"]["movies"]),
            "field": "radarr.movies",
        },
        "radarr_files": {
            "value": format_value(stats["radarr"]["files"]),
            "field": "radarr.files",
        },
        "radarr_monitored": {
            "value": format_value(stats["radarr"]["monitored"]),
            "field": "radarr.monitored",
        },
        "radarr_unmonitored": {
            "value": format_value(stats["radarr"]["unmonitored"]),
            "field": "radarr.unmonitored",
        },
        "radarr_size": {
            "value": stats["radarr"]["size"],
            "field": "radarr.size",
        },
    }

    for field_spec in fields_param.split(","):
        field_spec = field_spec.strip()
        # Check if a custom label is provided using the ':' separator
        if ":" in field_spec:
            field_key, custom_label = field_spec.split(":", 1)
            field_key = field_key.strip()
            custom_label = custom_label.strip()
        else:
            field_key, custom_label = field_spec, None

        # Only process fields that exist in the field_map
        if field_key in field_map:
            item = field_map[field_key].copy()
            # If a custom label is provided, use it
            if custom_label:
                item["label"] = custom_label
            # If not a header, generate a label from the field name
            elif item.get("type") != "header":
                item["label"] = field_key.replace("_", " ").title()
            # For headers, use the value as the label
            else:
                item["label"] = item["value"]
            ordered_data.append(item)

    return {"ordered_fields": ordered_data, "error": stats.get("error")}


def calculate_sonarr_stats(series_data):
    """
    Calculate statistics for Sonarr series data.

    Args:
        series_data (list): List of Sonarr series dictionaries.

    Returns:
        dict: Aggregated statistics for series, episodes, files, and disk size.
    """
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
        if series.get("ended", False) or series.get("status") == "ended":
            series_ended += 1
        elif series.get("status") == "continuing":
            series_continuing += 1

        # Monitoring status
        if series.get("monitored", False):
            monitored_series += 1
        else:
            unmonitored_series += 1

        # Episode statistics
        stats = series.get("statistics", {})
        total_episodes += stats.get("episodeCount", 0)
        episodes_with_files += stats.get("episodeFileCount", 0)
        total_size += stats.get("sizeOnDisk", 0)

    # Convert size to TB with customizable decimal places
    decimal_places = int(request.args.get("decimals", 1))
    total_size_tb = total_size / (1000**4) if total_size > 0 else 0
    size_formatted = f"{total_size_tb:.{decimal_places}f} TB"

    return {
        "series": total_series,
        "ended": series_ended,
        "continuing": series_continuing,
        "monitored": monitored_series,
        "unmonitored": unmonitored_series,
        "episodes": total_episodes,
        "files": episodes_with_files,
        "size": size_formatted,
    }


def calculate_radarr_stats(movies_data):
    """
    Calculate statistics for Radarr movies data.

    Args:
        movies_data (list): List of Radarr movie dictionaries.

    Returns:
        dict: Aggregated statistics for movies, files, monitored status, and disk size.
    """
    total_movies = len(movies_data)
    movies_with_files = 0
    monitored_movies = 0
    unmonitored_movies = 0
    total_size = 0

    for movie in movies_data:
        # File status
        if movie.get("hasFile", False):
            movies_with_files += 1

        # Monitoring status
        if movie.get("monitored", False):
            monitored_movies += 1
        else:
            unmonitored_movies += 1

        # Size calculation
        total_size += movie.get("sizeOnDisk", 0)

    # Convert size to TB with customizable decimal places
    decimal_places = int(request.args.get("decimals", 1))
    total_size_tb = total_size / (1000**4) if total_size > 0 else 0
    size_formatted = f"{total_size_tb:.{decimal_places}f} TB"

    return {
        "movies": total_movies,
        "files": movies_with_files,
        "monitored": monitored_movies,
        "unmonitored": unmonitored_movies,
        "size": size_formatted,
    }


@app.route("/api/agenda")
def get_agenda():
    """
    API endpoint to get a combined agenda of upcoming TV and movie releases.

    Returns:
        Response: JSON list of agenda items grouped by date.
    """
    all_items = []

    start_date = datetime.utcnow().strftime("%Y-%m-%d")
    sonarr_end_date = (datetime.utcnow() + timedelta(days=SONARR_DAYS_AHEAD)).strftime(
        "%Y-%m-%d"
    )
    radarr_end_date = (datetime.utcnow() + timedelta(days=RADARR_DAYS_AHEAD)).strftime(
        "%Y-%m-%d"
    )

    # Fetch data from Sonarr
    try:
        sonarr_endpoint = f"{SONARR_URL}/api/v3/calendar?start={start_date}&end={sonarr_end_date}&includeSeries=true"
        headers = {"X-Api-Key": SONARR_API_KEY}
        response = requests.get(sonarr_endpoint, headers=headers, timeout=10)
        response.raise_for_status()
        sonarr_data = response.json()
        for item in sonarr_data:
            all_items.append(normalize_sonarr_item(item))
    except requests.exceptions.RequestException as e:
        print(f"Error fetching from Sonarr: {e}")

    # Fetch data from Radarr
    try:
        radarr_endpoint = (
            f"{RADARR_URL}/api/v3/calendar?start={start_date}&end={radarr_end_date}"
        )
        headers = {"X-Api-Key": RADARR_API_KEY}
        response = requests.get(radarr_endpoint, headers=headers, timeout=10)
        response.raise_for_status()
        radarr_data = response.json()
        for item in radarr_data:
            normalized_item = normalize_radarr_item(item)
            if (
                normalized_item.get("release_datetime")
                and normalized_item["release_datetime"][:10] >= start_date
            ):
                all_items.append(normalized_item)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching from Radarr: {e}")

    # Sort all collected items by their release datetime
    all_items.sort(key=lambda x: x.get("release_datetime"))

    # Group the sorted items by date
    grouped_agenda = {}
    for item in all_items:
        if item.get("release_datetime"):
            date_key = item["release_datetime"][:10]
            if date_key not in grouped_agenda:
                grouped_agenda[date_key] = []
            grouped_agenda[date_key].append(item)

    agenda_list = []
    for date, items in grouped_agenda.items():
        agenda_list.append({"date": date, "items": items})

    return jsonify(agenda_list)


@app.route("/api/stats")
def get_stats():
    """
    API endpoint to get combined statistics from Sonarr and Radarr.

    Returns:
        Response: JSON statistics, optionally ordered by custom fields.
    """
    # Get fields parameter for custom ordering
    fields_param = request.args.get("fields", "")

    stats = {"sonarr": {}, "radarr": {}, "error": None}

    # Fetch Sonarr series data
    try:
        sonarr_endpoint = f"{SONARR_URL}/api/v3/series"
        headers = {"X-Api-Key": SONARR_API_KEY}
        response = requests.get(sonarr_endpoint, headers=headers, timeout=10)
        response.raise_for_status()
        sonarr_data = response.json()
        stats["sonarr"] = calculate_sonarr_stats(sonarr_data)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching Sonarr stats: {e}")
        stats["error"] = f"Sonarr error: {str(e)}"
        decimal_places = int(request.args.get("decimals", 1))
        stats["sonarr"] = {
            "series": 0,
            "ended": 0,
            "continuing": 0,
            "monitored": 0,
            "unmonitored": 0,
            "episodes": 0,
            "files": 0,
            "size": f"0.{'0' * decimal_places} TB",
        }

    # Fetch Radarr movies data
    try:
        radarr_endpoint = f"{RADARR_URL}/api/v3/movie"
        headers = {"X-Api-Key": RADARR_API_KEY}
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
        decimal_places = int(request.args.get("decimals", 1))
        stats["radarr"] = {
            "movies": 0,
            "files": 0,
            "monitored": 0,
            "unmonitored": 0,
            "size": f"0.{'0' * decimal_places} TB",
        }

    # Return ordered format if fields parameter is provided
    if fields_param:
        return jsonify(format_ordered_stats(stats, fields_param))
    else:
        return jsonify(stats)  # Default format


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
