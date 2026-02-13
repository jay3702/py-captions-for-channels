# Query Channels Recordings Tool

A command-line tool to query the Channels DVR API and display or export recordings data to CSV.

## Usage

### Basic Text Output

Display recordings with default columns (title, created_at, duration, path):

```bash
python scripts/query_channels_recordings.py
```

### Custom Columns

Specify which columns to display:

```bash
python scripts/query_channels_recordings.py -c title,created_at,path
python scripts/query_channels_recordings.py --columns title,aired_at,duration
```

### CSV Export (for Excel)

Export to a CSV file that Excel can open:

```bash
python scripts/query_channels_recordings.py -x -f recordings.csv
python scripts/query_channels_recordings.py -x -f output.csv -c title,path,created_at
python scripts/query_channels_recordings.py --excel --file data.csv --columns title,duration
```

## Arguments

Short and long forms are available for all arguments:

- `-c`, `--columns` - Comma-delimited list of column names
- `-x`, `--excel` - Export to CSV format (requires -f)
- `-f`, `--file` - Output filename for CSV export

## Configuration

The script reads the Channels DVR API URL from your `.env` file:

```bash
CHANNELS_API_URL=http://192.168.3.150:8089
```

Alternatively, you can override it for a single run:

```bash
# Windows PowerShell
$env:CHANNELS_API_URL="http://192.168.3.150:8089"; python scripts/query_channels_recordings.py

# Linux/Mac
CHANNELS_API_URL="http://192.168.3.150:8089" python scripts/query_channels_recordings.py
```

## Dependencies

No external dependencies required! The script uses Python's built-in `csv` module for exports.

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
