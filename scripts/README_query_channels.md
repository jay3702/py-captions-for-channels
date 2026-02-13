# Query Channels Recordings Tool

A command-line tool to query the Channels DVR API and display or export recordings data.

## Usage

### Basic Text Output

Display recordings with default columns (title, created_at, duration, path):

```bash
python scripts/query_channels_recordings.py
```

### Custom Columns

Specify which columns to display:

```bash
python scripts/query_channels_recordings.py -columns title,created_at,path
python scripts/query_channels_recordings.py -columns title,aired_at,completed,processed
```

### Excel Export

Export to an Excel file:

```bash
python scripts/query_channels_recordings.py -excel -file recordings.xlsx
python scripts/query_channels_recordings.py -excel -file output.xlsx -columns title,path,completed
```

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

For Excel export functionality, install openpyxl:

```bash
pip install openpyxl
```

Or install all development dependencies:

```bash
pip install -r requirements-dev.txt
```

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
