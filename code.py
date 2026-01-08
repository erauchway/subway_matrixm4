import time
import json
from adafruit_matrixportal.matrix import Matrix
from adafruit_matrixportal.network import Network
import displayio
import terminalio
from adafruit_display_text import label, bitmap_label
import adafruit_display_text.scrolling_label as scrolling_label
import board

class TrainTimeParser:
    """
    Parse train API with accurate time from Adafruit IO.
    Handles timezone differences between API (Eastern) and Adafruit IO (UTC).
    """

    def __init__(self, secrets=None):
        """Initialize the parser"""
        self.network = None
        self.matrix = None
        self.display = None
        self.current_utc_time = None
        self.weather_data = None
        self.secrets = secrets

    def setup_display(self):
        """Initialize the LED matrix display"""
        self.matrix = Matrix(bit_depth=4)
        self.display = self.matrix.display

    def show_splash_screen(self):
        """Display the splash screen from mta.bmp"""
        try:
            # Create a group for the splash screen
            splash = displayio.Group()

            # Load the bitmap
            bitmap_file = open("mta.bmp", "rb")
            bitmap = displayio.OnDiskBitmap(bitmap_file)
            tile_grid = displayio.TileGrid(
                bitmap,
                pixel_shader=bitmap.pixel_shader
            )

            splash.append(tile_grid)
            self.display.root_group = splash

            print("Splash screen displayed")

        except Exception as e:
            print(f"Could not load splash screen: {e}")
            # Continue without splash screen

    def connect(self):
        """Initialize network connection"""
        print("Connecting to network...")
        # Network class automatically reads from secrets.py
        self.network = Network(status_neopixel=None)
        print("Connected!")

    def get_current_time_utc(self):
        """
        Get current UTC time from network.
        Returns Unix timestamp in UTC.
        """
        # Get time from network
        time_response = self.network.get_local_time()

        # If it's already a number (epoch), use it directly
        if isinstance(time_response, (int, float)):
            self.current_utc_time = time_response
        # If it's a struct_time, convert it
        elif hasattr(time_response, 'tm_year'):
            self.current_utc_time = time.mktime(time_response)
        # If it's a string, parse the format: "2026-01-07 12:07:30.065 007 3 -0800 PST"
        elif isinstance(time_response, str):
            try:
                # Split and parse the datetime part
                parts = time_response.split()
                date_str = parts[0]  # "2026-01-07"
                time_str = parts[1]  # "12:07:30.065"
                tz_offset_str = parts[4] if len(parts) > 4 else "+0000"  # "-0800"

                # Parse date and time
                year, month, day = map(int, date_str.split('-'))
                hour, minute, second_float = time_str.split(':')
                hour = int(hour)
                minute = int(minute)
                second = int(float(second_float))

                # Create local timestamp
                local_time = time.mktime((year, month, day, hour, minute, second, 0, 0, -1))

                # Parse timezone offset (-0800 means UTC-8)
                tz_sign = 1 if tz_offset_str[0] == '+' else -1
                tz_hours = int(tz_offset_str[1:3])
                tz_minutes = int(tz_offset_str[3:5])
                tz_offset_seconds = tz_sign * (tz_hours * 3600 + tz_minutes * 60)

                # Convert to UTC
                self.current_utc_time = local_time - tz_offset_seconds

            except (ValueError, IndexError) as e:
                print(f"Warning: Could not parse time string: {e}, using time.time()")
                self.current_utc_time = time.time()
        else:
            # Fallback to current time
            print("Warning: Unknown time format, using time.time()")
            self.current_utc_time = time.time()

        return self.current_utc_time

    def parse_iso8601_to_utc(self, time_str):
        """
        Parse ISO 8601 time string and convert to UTC Unix timestamp.

        Args:
            time_str: ISO 8601 string like "2026-01-07T14:33:01-05:00"

        Returns:
            Unix timestamp in UTC
        """
        # Split into datetime and timezone parts
        if '+' in time_str:
            dt_part, tz_part = time_str.rsplit('+', 1)
            tz_sign = 1
        else:
            # Split on the last occurrence of '-' (timezone separator)
            parts = time_str.rsplit('-', 1)
            dt_part = parts[0]
            tz_part = parts[1] if len(parts) > 1 and ':' in parts[1] else '00:00'
            tz_sign = -1

        # Parse datetime
        date_part, time_part = dt_part.split('T')
        year, month, day = map(int, date_part.split('-'))
        hour, minute, second = map(int, time_part.split(':'))

        # Parse timezone offset
        tz_hours, tz_minutes = map(int, tz_part.split(':'))
        tz_offset_seconds = tz_sign * (tz_hours * 3600 + tz_minutes * 60)

        # Create timestamp in local time (as specified by the timezone)
        local_timestamp = time.mktime((year, month, day, hour, minute, second, 0, 0, -1))

        # Convert to UTC by subtracting the timezone offset
        utc_timestamp = local_timestamp - tz_offset_seconds

        return utc_timestamp

    def fetch_train_data(self, station_id="A31"):
        """
        Fetch train data from API.

        Args:
            station_id: Station ID (default "A31")

        Returns:
            JSON response as dict
        """
        url = f"https://api.wheresthefuckingtrain.com/by-id/{station_id}"
        print(f"Fetching: {url}")

        # Use network.fetch() to get the response object
        response = self.network.fetch(url)

        # The response object has a json() method
        return response.json()

    def fetch_weather_data(self, city="New York,US"):
        """
        Fetch weather data from OpenWeather API.

        Args:
            city: City name (default "New York,US")

        Returns:
            dict with 'description' and 'temp_f' keys
        """
        try:
            # Get API key from secrets
            api_key = self.secrets.get('openweather_key')

            if not api_key:
                print("Error: openweather_key not found in secrets")
                return {'description': 'No API Key', 'temp_f': 0}

            url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=imperial"
            print(f"Fetching weather from OpenWeather API...")

            response = self.network.fetch(url)
            data = response.json()

            # Extract weather description and temperature
            weather_list = data.get('weather', [{}])
            if weather_list and len(weather_list) > 0:
                description = str(weather_list[0].get('description', 'Unknown'))
                # Manually capitalize first letter of each word
                words = description.split(' ')
                capitalized_words = []
                for word in words:
                    if len(word) > 0:
                        # Manually capitalize: uppercase first char, lowercase rest
                        cap_word = word[0].upper() + word[1:].lower() if len(word) > 1 else word[0].upper()
                        capitalized_words.append(cap_word)
                description = ' '.join(capitalized_words)
            else:
                description = 'Unknown'

            temp_f = int(data.get('main', {}).get('temp', 0))

            self.weather_data = {
                'description': description,
                'temp_f': temp_f
            }

            print(f"Weather: {description}, {temp_f}°F")
            return self.weather_data

        except Exception as e:
            print(f"Error fetching weather: {e}")
            import traceback
            traceback.print_exception(e, e, e.__traceback__)
            return {'description': 'Unknown', 'temp_f': 0}

    def parse_train_times(self, json_response, min_minutes=5):
        """
        Parse train API response and return trains departing in more than min_minutes.

        Args:
            json_response: JSON dict from the API
            min_minutes: Minimum minutes from now (default 5)

        Returns:
            dict with 'northbound' and 'southbound' keys, each containing
            a list of dicts with 'route', 'minutes_until', and 'time' keys
        """
        # Get current UTC time from Adafruit IO
        current_utc = self.get_current_time_utc()

        result = {
            'northbound': [],
            'southbound': []
        }

        # Extract the first station data
        if 'data' not in json_response or len(json_response['data']) == 0:
            return result

        station_data = json_response['data'][0]

        # Process Northbound trains
        if 'N' in station_data:
            for train in station_data['N']:
                train_utc = self.parse_iso8601_to_utc(train['time'])
                minutes = int((train_utc - current_utc) / 60)

                if minutes > min_minutes:
                    result['northbound'].append({
                        'route': train['route'],
                        'minutes_until': minutes,
                        'time': train['time']
                    })

        # Process Southbound trains
        if 'S' in station_data:
            for train in station_data['S']:
                train_utc = self.parse_iso8601_to_utc(train['time'])
                minutes = int((train_utc - current_utc) / 60)

                if minutes > min_minutes:
                    result['southbound'].append({
                        'route': train['route'],
                        'minutes_until': minutes,
                        'time': train['time']
                    })

        return result

    def get_next_trains_by_route(self, parsed_data):
        """
        Organize parsed train data by route.

        Args:
            parsed_data: Output from parse_train_times()

        Returns:
            dict with routes as keys, each containing 'northbound' and 'southbound' times
        """
        routes = {}

        # Process northbound
        for train in parsed_data['northbound']:
            route = train['route']
            if route not in routes:
                routes[route] = {'northbound': None, 'southbound': None}
            if routes[route]['northbound'] is None:
                routes[route]['northbound'] = train['minutes_until']

        # Process southbound
        for train in parsed_data['southbound']:
            route = train['route']
            if route not in routes:
                routes[route] = {'northbound': None, 'southbound': None}
            if routes[route]['southbound'] is None:
                routes[route]['southbound'] = train['minutes_until']

        return routes


def create_degree_symbol():
    """
    Create a small bitmap for the degree symbol (°).
    Returns a displayio.TileGrid with a 3x3 pixel circle.
    """
    # Create a 3x3 bitmap for the degree symbol
    bitmap = displayio.Bitmap(3, 3, 2)
    palette = displayio.Palette(2)
    palette[0] = 0x000000  # Transparent
    palette[1] = 0xFFFFFF  # White (will be colored by parent group)
    palette.make_transparent(0)

    # Draw a small circle (ring)
    # Top and bottom rows: middle pixel only
    bitmap[1, 0] = 1
    bitmap[1, 2] = 1
    # Middle row: left and right pixels only (hollow)
    bitmap[0, 1] = 1
    bitmap[2, 1] = 1

    return displayio.TileGrid(bitmap, pixel_shader=palette)


# MTA Route colors (official colors)
MTA_ROUTE_COLORS = {
    'A': 0x0039A6,  # Blue
    'C': 0x0039A6,  # Blue
    'E': 0x0039A6,  # Blue
    'B': 0xFF6319,  # Orange
    'D': 0xFF6319,  # Orange
    'F': 0xFF6319,  # Orange
    'M': 0xFF6319,  # Orange
    'G': 0x6CBE45,  # Light Green
    'J': 0x996633,  # Brown
    'Z': 0x996633,  # Brown
    'L': 0xA7A9AC,  # Gray
    'N': 0xFCCC0A,  # Yellow
    'Q': 0xFCCC0A,  # Yellow
    'R': 0xFCCC0A,  # Yellow
    'W': 0xFCCC0A,  # Yellow
    '1': 0xEE352E,  # Red
    '2': 0xEE352E,  # Red
    '3': 0xEE352E,  # Red
    '4': 0x00933C,  # Green
    '5': 0x00933C,  # Green
    '6': 0x00933C,  # Green
    '7': 0xB933AD,  # Purple
    'S': 0x808183,  # Gray (Shuttle)
}


def create_route_badge(route, scale=1):
    """
    Create a displayio group with a route badge (letter in colored circle).

    Args:
        route: Route letter/number (e.g., 'A', 'C', 'E', 'L')
        scale: Scale factor (default 1)

    Returns:
        displayio.Group containing the badge
    """
    group = displayio.Group(scale=scale)

    # Get route color
    color = MTA_ROUTE_COLORS.get(route, 0xFFFFFF)

    # Create a colored circle bitmap (12x12 pixels - even number for centering)
    circle_size = 12
    bitmap = displayio.Bitmap(circle_size, circle_size, 2)
    palette = displayio.Palette(2)
    palette[0] = 0x000000  # Transparent/black
    palette[1] = color  # Route color
    palette.make_transparent(0)  # Make background transparent

    # Draw a filled circle
    center = circle_size / 2.0
    for y in range(circle_size):
        for x in range(circle_size):
            dx = x - center + 0.5
            dy = y - center + 0.5
            if dx*dx + dy*dy <= (center)**2:
                bitmap[x, y] = 1

    tile_grid = displayio.TileGrid(bitmap, pixel_shader=palette)
    group.append(tile_grid)

    # Add the route letter/number centered with BLACK text
    # Use terminalio.FONT for badges as it looks better in the small circles
    text_label = label.Label(
        terminalio.FONT,
        text=route,
        color=0x000000,  # Black text for better contrast
        x=3 if len(route) == 1 else 2,
        y=6
    )
    group.append(text_label)

    return group


def format_train_text_with_badges(trains, direction):
    """
    Format train data for display with route badges.

    Args:
        trains: List of train dicts with 'route' and 'minutes_until'
        direction: "N" or "S" for display

    Returns:
        List of tuples (route, times_string) for each route
    """
    if not trains:
        return []

    # Group by route for compact display
    route_times = {}
    for train in trains:
        route = train['route']
        mins = train['minutes_until']
        if route not in route_times:
            route_times[route] = []
        route_times[route].append(mins)

    # Create list of (route, times) tuples
    result = []
    for route in sorted(route_times.keys()):
        times = ','.join(str(t) for t in route_times[route][:3])
        result.append((route, times))

    return result


def create_scrolling_display(parser, trains, weather=None):
    """
    Create and update the scrolling display with route badges and weather.

    Args:
        parser: TrainTimeParser instance
        trains: Parsed train data
        weather: Weather data dict with 'description' and 'temp_f' (optional)
    """
    print(f"Northbound count: {len(trains['northbound'])}")
    print(f"Southbound count: {len(trains['southbound'])}")

    # Create a fresh display group
    main_group = displayio.Group()

    # Format data for north and south
    north_data = format_train_text_with_badges(trains['northbound'], "N")
    south_data = format_train_text_with_badges(trains['southbound'], "S")

    # Create southbound display (bottom half) - Downtown
    south_scroll_group = displayio.Group()
    south_scroll_group.y = 20

    # Build the entire line: Downtown label, badges, times, then temperature
    x_offset = 0

    # Add "Downtown: " label
    s_label = label.Label(
        terminalio.FONT,
        text="Downtown: ",
        color=0x6BB6FF,
        x=x_offset,
        y=4
    )
    south_scroll_group.append(s_label)
    x_offset += len("Downtown: ") * 6

    # Add each route badge and times
    for route, times in south_data:
        # Add badge
        badge = create_route_badge(route)
        badge.x = x_offset
        badge.y = -2
        south_scroll_group.append(badge)
        x_offset += 15  # Badge width (12) + 3 pixels spacing

        # Add times
        times_label = label.Label(
            terminalio.FONT,
            text=f"{times} ",
            color=0x6BB6FF,
            x=x_offset,
            y=4
        )
        south_scroll_group.append(times_label)
        x_offset += len(times) * 6 + 6

    # Add temperature at the end if available with custom degree symbol
    if weather:
        # Add some spacing before temperature
        x_offset += 12

        # Add temperature number
        temp_label = label.Label(
            terminalio.FONT,
            text=f"{weather['temp_f']}",
            color=0x6BB6FF,
            x=x_offset,
            y=4
        )
        south_scroll_group.append(temp_label)
        x_offset += len(str(weather['temp_f'])) * 6

        # Add degree symbol bitmap
        degree_symbol = create_degree_symbol()
        degree_group = displayio.Group()
        degree_group.append(degree_symbol)
        degree_group.x = x_offset
        degree_group.y = 1  # Raise it up to be superscript-like

        # Color the degree symbol
        for i in range(len(degree_symbol.pixel_shader)):
            if not degree_symbol.pixel_shader.is_transparent(i):
                degree_symbol.pixel_shader[i] = 0x6BB6FF

        south_scroll_group.append(degree_group)
        x_offset += 4  # Width of degree symbol + small space

        # Add "F"
        f_label = label.Label(
            terminalio.FONT,
            text="F",
            color=0x6BB6FF,
            x=x_offset,
            y=4
        )
        south_scroll_group.append(f_label)
        x_offset += len("F") * 6

    south_width = x_offset

    # Create northbound display (top half) - Uptown
    north_scroll_group = displayio.Group()
    north_scroll_group.y = 4

    # Build the entire line: Uptown label, badges, times, then description
    x_offset = 0

    # Add "Uptown: " label
    n_label = label.Label(
        terminalio.FONT,
        text="Uptown: ",
        color=0xFF8C40,
        x=x_offset,
        y=4
    )
    north_scroll_group.append(n_label)
    x_offset += len("Uptown: ") * 6

    # Add each route badge and times
    for route, times in north_data:
        # Add badge
        badge = create_route_badge(route)
        badge.x = x_offset
        badge.y = -2
        north_scroll_group.append(badge)
        x_offset += 15  # Badge width (12) + 3 pixels spacing

        # Add times
        times_label = label.Label(
            terminalio.FONT,
            text=f"{times} ",
            color=0xFF8C40,
            x=x_offset,
            y=4
        )
        north_scroll_group.append(times_label)
        x_offset += len(times) * 6 + 6

    # Add weather description at the end if available
    if weather:
        # Add some spacing before description
        x_offset += 12

        desc_label = label.Label(
            terminalio.FONT,
            text=f"{weather['description']}",
            color=0xFF8C40,
            x=x_offset,
            y=4
        )
        north_scroll_group.append(desc_label)
        x_offset += len(weather['description']) * 6

    north_width = x_offset

    # Wrap in container groups for scrolling
    north_container = displayio.Group()
    north_container.append(north_scroll_group)

    south_container = displayio.Group()
    south_container.append(south_scroll_group)

    # Add both to main group
    main_group.append(south_container)
    main_group.append(north_container)

    # Show the group
    parser.display.root_group = main_group
    parser.display.refresh()

    # Return the scroll groups and their content widths for animation
    return north_scroll_group, south_scroll_group, north_width, south_width, parser.display.width


# Example usage with secrets.py file:
"""
Create a secrets.py file with:

secrets = {
    'ssid': 'your_wifi_ssid',
    'password': 'your_wifi_password',
    'aio_username': 'your_aio_username',
    'aio_key': 'your_aio_key'
}
"""

# Example code.py:
if __name__ == "__main__":
    # Import secrets
    try:
        from secrets import secrets
    except ImportError:
        print("WiFi secrets not found in secrets.py")
        raise

    # Initialize parser with secrets
    parser = TrainTimeParser(secrets)

    # Setup display
    parser.setup_display()

    # Show splash screen
    parser.show_splash_screen()
    time.sleep(2)  # Show splash for 2 seconds

    # Connect to network
    parser.connect()

    # Track startup time for 20-minute timeout
    startup_time = time.monotonic()
    run_duration = 20 * 60  # 20 minutes in seconds

    # Initial fetch of both weather and trains
    print("\nFetching initial weather data...")
    weather = parser.fetch_weather_data("New York,US")
    last_weather_update = time.monotonic()

    # Main loop
    north_group = None
    south_group = None
    north_width = 0
    south_width = 0
    display_width = parser.display.width

    while True:
        try:
            # Check if 20 minutes have elapsed
            current_time = time.monotonic()
            if current_time - startup_time >= run_duration:
                print("\n20 minutes elapsed - going dormant")
                # Clear the display
                blank_group = displayio.Group()
                parser.display.root_group = blank_group
                parser.display.refresh()
                # Turn off display brightness
                parser.display.brightness = 0
                print("Display off. Press Reset to restart.")
                # Infinite sleep loop
                while True:
                    time.sleep(3600)  # Sleep indefinitely

            # Check if we need to update weather (every 10 minutes = 600 seconds)
            if current_time - last_weather_update >= 600:
                print("\nFetching weather data...")
                weather = parser.fetch_weather_data("New York,US")
                last_weather_update = current_time

            # Fetch and parse train data (every loop = every minute)
            print("\nFetching train data...")
            train_data = parser.fetch_train_data("A31")
            trains = parser.parse_train_times(train_data, min_minutes=5)

            print("\nNorthbound trains (>5 min):")
            for train in trains['northbound']:
                print(f"  Route {train['route']}: {train['minutes_until']} min")

            print("\nSouthbound trains (>5 min):")
            for train in trains['southbound']:
                print(f"  Route {train['route']}: {train['minutes_until']} min")

            # Only create display on first run, otherwise reuse
            if north_group is None:
                # Create/update display with weather
                north_group, south_group, north_width, south_width, display_width = create_scrolling_display(parser, trains, weather)
            else:
                # Just update the existing display with new data
                # For now, recreate since updating is complex
                # Free old groups first
                north_group = None
                south_group = None
                import gc
                gc.collect()  # Force garbage collection

                north_group, south_group, north_width, south_width, display_width = create_scrolling_display(parser, trains, weather)

            # Manual scrolling animation - each line loops independently
            north_position = 0
            south_position = 0

            for i in range(600):  # Scroll for ~60 seconds
                # Scroll north left by 1 pixel
                north_position -= 1
                # When content fully scrolls off left, jump back to right edge
                if north_position <= -north_width:
                    north_position = display_width
                north_group.x = north_position

                # Scroll south left by 1 pixel (independently)
                south_position -= 1
                # When content fully scrolls off left, jump back to right edge
                if south_position <= -south_width:
                    south_position = display_width
                south_group.x = south_position

                time.sleep(0.1)

        except Exception as e:
            print(f"Error: {e}")
            import gc
            gc.collect()  # Try to free memory
            time.sleep(10)  # Wait before retrying
