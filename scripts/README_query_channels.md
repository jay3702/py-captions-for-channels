# Query Channels Recordings Tool

A command-line tool to query the Channels DVR API and display or export recordings data to CSV.

The tool automatically discovers the Channels DVR API endpoint from the py-captions web app, making it easy to use from any machine without configuration.

## Usage

### Basic Text Output

Display recordings with default columns (title, created_at, duration, path):

```bash
python scripts/query_channels_recordings.py
python scripts/query_channels_recordings.py -w http://192.168.3.150:8000
```

### Custom Columns

Specify which columns to display:

```bash
python scripts/query_channels_recordings.py -c title,created_at,path
python scripts/query_channels_recordings.py -w http://192.168.3.150:8000 -c title,aired_at,duration
```

### CSV Export (for Excel)

Export to a CSV file that Excel can open:

```bash
python scripts/query_channels_recordings.py -x -f recordings.csv
python scripts/query_channels_recordings.py -w http://192.168.3.150:8000 -x -f output.csv -c title,path,created_at
```

## Arguments

Short and long forms are available for all arguments:

- `-w`, `--webapp` - Web app URL (default: http://localhost:8000)
- `-c`, `--columns` - Comma-delimited list of column names
- `-x`, `--excel` - Export to CSV format (requires -f)
- `-f`, `--file` - Output filename for CSV export

## How It Works

The script connects to the py-captions web app and retrieves the Channels DVR API URL from the `/api/status` endpoint. This means:

1. **No local configuration needed** - Works from any machine
2. **Always uses the correct server** - Gets the URL from your deployed instance
3. **Simple to use** - Just point it at your web app

## Examples

```bash
# Query from Windows dev machine to deployed server
python scripts/query_channels_recordings.py -w http://192.168.3.150:8000

# Export all recordings to CSV
python scripts/query_channels_recordings.py -w http://192.168.3.150:8000 -x -f recordings.csv

# Get specific columns
python scripts/query_channels_recordings.py -w http://192.168.3.150:8000 -c title,duration,channel_number
```

## Dependencies

No external dependencies beyond Python's standard library! The script uses only built-in modules:
- `requests` (already in requirements.txt)

## Common Columns

Available columns from the Channels DVR API include:

**Direct Fields:**
- `path` - File path
- `created_at` - Creation timestamp
- `updated_at` - Last update timestamp
- `duration` - Recording duration (seconds)
- `id` - Recording ID
- `job_id` - Job ID
- `channel_number` - Channel number
- `device_id` - Device ID

**Nested Fields (from Airing):**
- `title` - Recording title
- `summary` - Brief description
- `aired_at` - Original air date timestamp
- `original_date` - Original air date
- `channel` - Channel ID
- `series_id` - Series ID
- `program_id` - Program ID
- `episode_number` - Episode number
- `release_year` - Release year
- `image` - Thumbnail image URL
- `categories` - List of categories
- `genres` - List of genres

**Notes:**
- Datetime columns (created_at, updated_at, aired_at) are automatically formatted to human-readable format.
- You can use either lowercase (title, created_at) or PascalCase (Title, CreatedAt) - the script handles both.
- Nested fields like `title` are automatically mapped from `Airing.Title`.
