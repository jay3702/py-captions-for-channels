# Query Channels Recordings Tool

A command-line tool to query the Channels DVR API and display or export recordings data.

## Usage

### Basic Text Output

Display recordings with default columns (created_at, updated_at, completed, processed, path):

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

- `title` - Recording title
- `path` - File path
- `created_at` - Creation timestamp
- `updated_at` - Last update timestamp
- `aired_at` - Original air date timestamp
- `completed` - Whether processing is complete (boolean)
- `processed` - Whether recording has been processed (boolean)
- `duration` - Recording duration
- `size` - File size in bytes

Datetime columns (created_at, updated_at, aired_at) are automatically formatted to human-readable format.
