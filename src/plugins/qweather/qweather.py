from plugins.base_plugin.base_plugin import BasePlugin
from PIL import Image
import os
import requests
import logging
import json
from datetime import datetime, timezone, date, timedelta
from astral import moon
import pytz
from io import BytesIO
import math
import re

logger = logging.getLogger(__name__)

def get_moon_phase_name(phase_age: float) -> str:
    PHASES_THRESHOLDS = [
        (1.0, "newmoon"),
        (7.0, "waxingcrescent"),
        (8.5, "firstquarter"),
        (14.0, "waxinggibbous"),
        (15.5, "fullmoon"),
        (22.0, "waninggibbous"),
        (23.5, "lastquarter"),
        (29.0, "waningcrescent"),
    ]

    for threshold, phase_name in PHASES_THRESHOLDS:
        if phase_age <= threshold:
            return phase_name
    return "newmoon"

UNITS = {
    "metric": {
        "temperature": "°C",
        "speed": "km/h"
    },
    "imperial": {
        "temperature": "°F",
        "speed": "mph"
    }
}

LABELS = {
    "zh": {
        "feels_like": "体感温度",
        "sunrise": "日出",
        "sunset": "日落",
        "wind": "风速",
        "humidity": "湿度",
        "pressure": "气压",
        "uv_index": "紫外线",
        "visibility": "能见度",
        "air_quality": "空气质量",
        "last_refresh": "最后更新",
        "weather_alert": "天气预警"
    },
    "en": {
        "feels_like": "Feels Like",
        "sunrise": "Sunrise",
        "sunset": "Sunset",
        "wind": "Wind",
        "humidity": "Humidity",
        "pressure": "Pressure",
        "uv_index": "UV Index",
        "visibility": "Visibility",
        "air_quality": "Air Quality",
        "last_refresh": "Last refresh",
        "weather_alert": "Weather Alert"
    }
}

QWEATHER_ICON_MAP = {
    # Day icons
    "100": "01d",  # Clear/Sunny
    "101": "02d",  # Cloudy
    "102": "02d",  # Few clouds
    "103": "03d",  # Overcast
    "104": "04d",  # Overcast
    # Night icons
    "150": "01n",  # Clear night
    "151": "02n",  # Cloudy night
    "152": "02n",  # Few clouds night
    "153": "03n",  # Overcast night
    "154": "04n",  # Overcast night
    "300": "09d",
    "301": "09d",
    "302": "10d",
    "303": "11d",
    "304": "11d",
    "305": "10d",
    "306": "10d",
    "307": "10d",
    "308": "10d",
    "309": "09d",
    "310": "10d",
    "311": "10d",
    "312": "10d",
    "313": "10d",
    "314": "09d",
    "315": "10d",
    "316": "10d",
    "317": "10d",
    "318": "10d",
    "350": "09d",
    "351": "09d",
    "399": "10d",
    "400": "13d",
    "401": "13d",
    "402": "13d",
    "403": "13d",
    "404": "13d",
    "405": "13d",
    "406": "13d",
    "407": "13d",
    "408": "13d",
    "409": "13d",
    "410": "13d",
    "456": "13d",
    "457": "13d",
    "499": "13d",
    "500": "50d",
    "501": "50d",
    "502": "50d",
    "503": "50d",
    "504": "50d",
    "507": "50d",
    "508": "50d",
    "509": "50d",
    "510": "50d",
    "511": "50d",
    "512": "50d",
    "513": "50d",
    "514": "50d",
    "515": "50d",
    "800": "01d",
    "801": "02d",
    "802": "03d",
    "803": "04d",
    "804": "04d",
    "805": "04d",
    "806": "04d",
    "807": "04d"
}

# Map QWeather day icon codes to night icon codes
QWEATHER_DAY_TO_NIGHT = {
    "100": "150",  # Clear -> Clear night
    "101": "151",  # Cloudy -> Cloudy night
    "102": "152",  # Few clouds -> Few clouds night
    "103": "153",  # Overcast -> Overcast night
    "104": "154",  # Overcast -> Overcast night
}

class QWeather(BasePlugin):
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['api_key'] = {
            "required": True,
            "service": "QWeather (和风天气)",
            "expected_key": "QWEATHER_API_KEY"
        }
        template_params['style_settings'] = True
        return template_params

    def _get_cache_dir(self):
        """Get the cache directory path."""
        cache_dir = os.path.join(self.get_plugin_dir(), 'cache')
        os.makedirs(cache_dir, exist_ok=True)
        return cache_dir

    def _get_cached_data(self, cache_key, api_func, cache_minutes):
        """
        Get data from cache or fetch from API.

        Args:
            cache_key: Unique identifier for the cache file
            api_func: Function to call if cache is expired/missing
            cache_minutes: Cache expiration time in minutes

        Returns:
            Cached or fresh data
        """
        cache_dir = self._get_cache_dir()
        cache_file = os.path.join(cache_dir, f'{cache_key}.json')

        # Check if cache exists and is valid
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    cached = json.load(f)
                    cache_time = datetime.fromisoformat(cached.get('time', ''))
                    if datetime.now() - cache_time < timedelta(minutes=cache_minutes):
                        logger.info(f"Using cached data for {cache_key} (age: {(datetime.now() - cache_time).seconds} seconds)")
                        return cached['data']
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                logger.warning(f"Failed to read cache for {cache_key}: {e}")

        # Fetch fresh data
        logger.info(f"Fetching fresh data for {cache_key}")
        data = api_func()

        # Save to cache
        try:
            with open(cache_file, 'w') as f:
                json.dump({
                    'time': datetime.now().isoformat(),
                    'data': data
                }, f)
            logger.info(f"Cached data for {cache_key} for {cache_minutes} minutes")
        except Exception as e:
            logger.warning(f"Failed to cache data for {cache_key}: {e}")

        return data

    def generate_image(self, settings, device_config):
        # Store settings for debug access
        self.current_settings = settings
        
        lat = settings.get('latitude')
        long = settings.get('longitude')
        if not lat or not long:
            raise RuntimeError("Latitude and Longitude are required.")

        units = settings.get('units', 'metric')
        if units not in ['metric', 'imperial']:
            raise RuntimeError("Units must be metric or imperial.")

        language = settings.get('language', 'zh')
        if language not in ['zh', 'en']:
            language = 'zh'

        theme_mode = settings.get('themeMode', 'light')
        if theme_mode not in ['light', 'dark', 'auto']:
            theme_mode = 'light'

        display_style = settings.get('displayStyle', 'default')
        if display_style not in ['default', 'nothing', 'qweather']:
            display_style = 'default'

        api_key = device_config.load_env_key("QWEATHER_API_KEY")
        if not api_key:
            raise RuntimeError("QWeather API Key not configured.")

        host = settings.get('qweatherHost') or device_config.load_env_key("QWEATHER_HOST") or 'https://devapi.qweather.com'
        title = settings.get('customTitle', '')

        mock_alert_headline = settings.get('mockAlertHeadline', '')
        mock_alert_severity = settings.get('mockAlertSeverity', '')

        if mock_alert_headline and not mock_alert_severity:
            mock_alert_severity = 'moderate'
            logger.warning(f"Mock alert headline provided without severity, defaulting to 'moderate'")

        timezone = device_config.get_config("timezone", default="Asia/Shanghai")
        time_format = device_config.get_config("time_format", default="24h")
        tz = pytz.timezone(timezone)

        try:
            location_id = self.get_location_id(host, api_key, lat, long)

            weather_data = self.get_weather_data(host, api_key, location_id, units)
            daily_forecast = self.get_daily_forecast(host, api_key, location_id, units)
            hourly_forecast = self.get_hourly_forecast(host, api_key, location_id, units)

            # Only call minutely API if mergeMinutelyData is enabled
            merge_minutely = settings.get("mergeMinutelyData", "false").lower() == "true"
            if merge_minutely:
                minutely_forecast = self.get_minutely_forecast(host, api_key, location_id)
            else:
                minutely_forecast = []

            air_quality = self.get_air_quality(host, api_key, location_id)
            weather_alerts = self.get_weather_alerts(host, api_key, lat, long)

            if mock_alert_headline:
                logger.info(f"Using mock weather alert: {mock_alert_headline}, severity: {mock_alert_severity}")
                weather_alerts = self.create_mock_alert(mock_alert_headline, '', mock_alert_severity)
                logger.info(f"Mock weather alerts created: {weather_alerts}")

            if not title:
                # Try to get location name from GeoAPI
                location_name = self.get_location_name(host, api_key, lat, long)
                if location_name:
                    title = location_name
                else:
                    # Fallback to formatted coordinates (2 decimal places)
                    title = f"{float(lat):.2f}, {float(long):.2f}"
                    logger.warning(f"Could not get location name, using coordinates: {title}")

            template_params, sunrise_dt, sunset_dt = self.parse_weather_data(
                weather_data,
                daily_forecast,
                minutely_forecast,
                hourly_forecast,
                air_quality,
                weather_alerts,
                tz,
                units,
                time_format,
                language,
                display_style,
                settings
            )
            template_params['title'] = title
            template_params['labels'] = LABELS[language]

            # Pass sunrise/sunset info to template for hourly chart
            template_params['sunrise_time'] = sunrise_dt.strftime("%H:%M") if sunrise_dt else None
            template_params['sunset_time'] = sunset_dt.strftime("%H:%M") if sunset_dt else None
            template_params['sunrise_icon'] = self.get_plugin_dir('icons/sunrise.png')
            template_params['sunset_icon'] = self.get_plugin_dir('icons/sunset.png')

            # Use sunrise/sunset time for theme determination (ensures theme switches correctly throughout the day)
            is_dark_mode = self.determine_theme(theme_mode, sunrise_dt, sunset_dt, tz)
            template_params['dark_mode'] = is_dark_mode
            template_params['display_style'] = display_style

            # Adjust background color based on theme
            if settings.get('backgroundOption') == 'color':
                settings = settings.copy()  # Create a copy to avoid modifying original
                if is_dark_mode:
                    settings['backgroundColor'] = '#000000'
                else:
                    settings['backgroundColor'] = '#FFFFFF'

        except Exception as e:
            logger.error(f"QWeather request failed: {str(e)}")
            raise RuntimeError(f"QWeather request failure: {str(e)}")

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        template_params["plugin_settings"] = settings

        now = datetime.now(tz)
        if time_format == "24h":
            last_refresh_time = now.strftime("%Y-%m-%d %H:%M")
        else:
            last_refresh_time = now.strftime("%Y-%m-%d %I:%M %p")
        template_params["last_refresh_time"] = last_refresh_time
        template_params["language"] = language

        image = self.render_image(dimensions, "qweather.html", "qweather.css", template_params)

        if not image:
            raise RuntimeError("Failed to take screenshot, please check logs.")
        return image

    def get_location_id(self, host, api_key, lat, long):
        return f"{long},{lat}"

    def get_location_name(self, host, api_key, lat, long):
        """Get location name from coordinates using QWeather GeoAPI"""
        # Format coordinates to 2 decimal places as required by QWeather API
        lat_formatted = f"{float(lat):.2f}"
        long_formatted = f"{float(long):.2f}"

        # Check if using custom host
        is_custom_host = 'qweatherapi.com' in host and 'devapi' not in host and 'api.qweather.com' not in host

        if is_custom_host:
            # Custom host uses /geo/ prefix with key parameter
            url = f"{host}/geo/v2/city/lookup"
        else:
            # Standard host
            url = f"{host}/v2/city/lookup"

        params = {
            "location": f"{long_formatted},{lat_formatted}",
            "key": api_key
        }
        logger.info(f"Requesting location name from: {url} with location: {params['location']}")

        try:
            response = requests.get(url, params=params, timeout=10)
            logger.info(f"Location API response status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Location API response: {data}")
                if data.get('code') == '200' and data.get('location') and len(data['location']) > 0:
                    loc = data['location'][0]
                    # Build location name from name, adm2, adm1
                    # Example: "东城 北京 北京市" or "Beijing Beijing"
                    parts = []
                    name = loc.get('name', '')
                    adm2 = loc.get('adm2', '')
                    adm1 = loc.get('adm1', '')

                    # Add unique parts (avoid duplication)
                    if name and name not in parts:
                        parts.append(name)
                    if adm2 and adm2 not in parts and adm2 != name:
                        parts.append(adm2)
                    if adm1 and adm1 not in parts and adm1 != adm2:
                        parts.append(adm1)

                    location_name = ' '.join(parts) if parts else loc.get('country', '')
                    logger.info(f"Found location name: {location_name}")
                    return location_name
                else:
                    logger.warning(f"Location API returned code: {data.get('code')}, locations: {data.get('location')}")
        except Exception as e:
            logger.error(f"Failed to get location name: {e}")

        return ""

    def get_weather_data(self, host, api_key, location_id, units):
        url = f"{host}/v7/weather/now"
        params = {
            "location": location_id,
            "key": api_key,
            "unit": "m" if units == "metric" else "i"
        }
        logger.info(f"Requesting weather data from: {url} with params: {params}")
        response = requests.get(url, params=params, timeout=(5, 30))
        logger.info(f"Response status: {response.status_code}")

        if response.status_code != 200:
            logger.error(f"Failed to retrieve weather data. Status: {response.status_code}, Content: {response.content}")
            raise RuntimeError(f"Failed to retrieve weather data. Status: {response.status_code}")

        try:
            data = response.json()
        except Exception as e:
            logger.error(f"Failed to parse JSON response: {e}, Content: {response.text}")
            raise RuntimeError("Failed to parse weather data.")

        if data.get('code') != '200':
            logger.error(f"Invalid weather response: {data}")
            raise RuntimeError("Failed to get valid weather data.")

        return data['now']

    def get_daily_forecast(self, host, api_key, location_id, units):
        cache_key = f"daily_{location_id}_{units}"

        def fetch_daily():
            url = f"{host}/v7/weather/7d"
            params = {
                "location": location_id,
                "key": api_key,
                "unit": "m" if units == "metric" else "i"
            }
            response = requests.get(url, params=params, timeout=(5, 30))

            if response.status_code != 200:
                logger.error(f"Failed to retrieve daily forecast. Status: {response.status_code}, Content: {response.content}")
                raise RuntimeError("Failed to retrieve daily forecast.")

            try:
                data = response.json()
            except Exception as e:
                logger.error(f"Failed to parse JSON response: {e}, Content: {response.text}")
                raise RuntimeError("Failed to parse forecast data.")

            if data.get('code') != '200':
                logger.error(f"Invalid forecast response: {data}")
                raise RuntimeError("Failed to get valid forecast data.")

            return data['daily']

        # Cache for 1 hour (60 minutes)
        return self._get_cached_data(cache_key, fetch_daily, 60)

    def get_hourly_forecast(self, host, api_key, location_id, units):
        url = f"{host}/v7/weather/24h"
        params = {
            "location": location_id,
            "key": api_key,
            "unit": "m" if units == "metric" else "i"
        }
        response = requests.get(url, params=params, timeout=(5, 30))

        if response.status_code != 200:
            logger.error(f"Failed to retrieve hourly forecast. Status: {response.status_code}, Content: {response.content}")
            raise RuntimeError("Failed to retrieve hourly forecast.")

        try:
            data = response.json()
        except Exception as e:
            logger.error(f"Failed to parse JSON response: {e}, Content: {response.text}")
            raise RuntimeError("Failed to parse hourly forecast data.")

        if data.get('code') != '200':
            logger.error(f"Invalid hourly forecast response: {data}")
            raise RuntimeError("Failed to get valid hourly forecast data.")

        return data['hourly']

    def get_minutely_forecast(self, host, api_key, location_id):
        url = f"{host}/v7/minutely/5m"
        params = {
            "location": location_id,
            "key": api_key
        }
        response = requests.get(url, params=params, timeout=(5, 30))

        if response.status_code != 200:
            logger.warning(f"Failed to retrieve minutely forecast. Status: {response.status_code}, falling back to hourly only")
            return []

        try:
            data = response.json()
        except Exception as e:
            logger.warning(f"Failed to parse minutely JSON response: {e}, falling back to hourly only")
            return []

        if data.get('code') != '200':
            logger.warning(f"Invalid minutely forecast response: {data}, falling back to hourly only")
            return []

        return data.get('minutely', [])

    def get_air_quality(self, host, api_key, location_id):
        cache_key = f"aqi_{location_id}"

        def fetch_aqi():
            long, lat = location_id.split(',')
            url = f"{host}/airquality/v1/current/{lat}/{long}"
            params = {
                "key": api_key
            }
            response = requests.get(url, params=params, timeout=(5, 30))

            if response.status_code != 200:
                logger.error(f"Failed to get air quality data: {response.content}")
                return {}

            try:
                data = response.json()
                if data.get('indexes') and len(data['indexes']) > 0:
                    cn_mee = data['indexes'][0]
                    return {
                        'aqi': cn_mee.get('aqi', 'N/A'),
                        'category': cn_mee.get('category', '')
                    }
            except Exception as e:
                logger.error(f"Failed to parse air quality response: {e}")

            return {}

        # Cache for 30 minutes
        return self._get_cached_data(cache_key, fetch_aqi, 30)

    def get_weather_alerts(self, host, api_key, lat, long):
        cache_key = f"alerts_{lat}_{long}"

        def fetch_alerts():
            url = f"{host}/weatheralert/v1/current/{lat}/{long}"
            params = {
                "key": api_key
            }
            response = requests.get(url, params=params, timeout=(5, 30))

            if response.status_code != 200:
                logger.error(f"Failed to get weather alerts: {response.content}")
                return []

            try:
                data = response.json()
                alerts = data.get('alerts', [])
                if alerts:
                    logger.info(f"Found {len(alerts)} weather alert(s)")
                return alerts
            except Exception as e:
                logger.error(f"Failed to parse weather alerts response: {e}")

            return []

        # Cache for 5 minutes
        return self._get_cached_data(cache_key, fetch_alerts, 5)

    def create_mock_alert(self, headline, description, severity):
        short_headline = headline
        for sep in ('：', ':'):
            if sep in headline:
                short_headline = headline.split(sep)[0].strip()
                break
        return [{
            'headline': headline,
            'short_headline': short_headline or headline,
            'description': description,
            'severity': severity,
            'eventType': {'name': short_headline or headline},
            'issuedTime': datetime.now().isoformat(),
            'expireTime': (datetime.now() + timedelta(hours=24)).isoformat()
        }]

    def parse_weather_data(self, weather_data, daily_forecast, minutely_forecast, hourly_forecast, air_quality, weather_alerts, tz, units, time_format, language="zh", display_style="default", settings=None):
        # Get sunrise and sunset times to determine if it's day or night
        # QWeather API doesn't return isDay field, so we need to calculate it
        now = datetime.now(tz)
        today_forecast = daily_forecast[0] if daily_forecast else {}

        sunrise_str = today_forecast.get('sunrise')
        sunset_str = today_forecast.get('sunset')

        is_day = '1'  # Default to day
        if sunrise_str and sunset_str:
            naive_sunrise = datetime.strptime(sunrise_str, "%H:%M").replace(
                year=now.year, month=now.month, day=now.day
            )
            naive_sunset = datetime.strptime(sunset_str, "%H:%M").replace(
                year=now.year, month=now.month, day=now.day
            )
            sunrise_dt = tz.localize(naive_sunrise)
            sunset_dt = tz.localize(naive_sunset)
            # Check if current time is between sunrise-30min and sunset
            # Transition to day mode 30 minutes before sunrise (sky starts getting brighter)
            sunrise_transition = sunrise_dt - timedelta(minutes=30)
            is_day = '1' if sunrise_transition <= now < sunset_dt else '0'
            logger.debug(f"Current time: {now}, Sunrise: {sunrise_dt}, Sunrise transition: {sunrise_transition}, Sunset: {sunset_dt}, is_day: {is_day}")

        current_icon = self.map_qweather_icon(weather_data.get('icon', '100'), display_style, is_day)
        current_temp = float(weather_data.get('temp', 0))
        feels_like = float(weather_data.get('feelsLike', current_temp))
        current_text = weather_data.get('text', '')  # 天气情况文字（如"晴"、"多云"）
        logger.info(f"Current weather text: '{current_text}'")

        if language == "zh":
            now = datetime.now(tz)
            weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            months = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"]
            current_date = f"{weekdays[now.weekday()]}, {months[now.month - 1]} {now.day}日"
        else:
            current_date = datetime.now(tz).strftime("%A, %B %d")

        data = {
            "current_date": current_date,
        }

        # Handle icon for qweather style
        if display_style == "qweather":
            # Fixed: Remove duplicate qweather in path
            svg_path = self.get_plugin_dir(f'icons/{current_icon}.svg')
            if os.path.exists(svg_path):
                data["current_day_icon"] = svg_path
            else:
                # Fallback to PNG if SVG doesn't exist
                data["current_day_icon"] = self.get_plugin_dir(f'icons/{current_icon}.png')
                logger.warning(f"SVG icon not found: {svg_path}, using PNG fallback: {data['current_day_icon']}")
        else:
            data["current_day_icon"] = self.get_plugin_dir(f'icons/{current_icon}.png')

        data.update({
            "current_day_icon_code": current_icon if display_style == "qweather" else "",
            "current_temperature": str(round(current_temp)),
            "current_text": current_text,  # 添加天气文字
            "feels_like": str(round(feels_like)),
            "temperature_unit": UNITS[units]["temperature"],
            "units": units,
            "time_format": time_format
        })

        data['forecast'] = self.parse_forecast(daily_forecast, tz, language, display_style, settings, air_quality, is_day)
        data['data_points'], sunrise_dt, sunset_dt = self.parse_data_points(weather_data, daily_forecast[0] if daily_forecast else {}, air_quality, tz, units, time_format, language, display_style)

        merge_minutely = settings.get("mergeMinutelyData", "false").lower() == "true"
        if merge_minutely:
            data['hourly_forecast'] = self.merge_minutely_and_hourly(minutely_forecast, hourly_forecast, tz, time_format, units, display_style)
        else:
            data['hourly_forecast'] = self.parse_hourly_forecast(hourly_forecast, tz, time_format, units, weather_data, display_style)

        data['weather_alerts'] = self.parse_weather_alerts(weather_alerts, language)

        if data['forecast']:
            forecast_temps = []
            for day in data['forecast']:
                forecast_temps.append(day['high'])
                forecast_temps.append(day['low'])
            data['forecast_temp_max'] = max(forecast_temps) if forecast_temps else 0
            data['forecast_temp_min'] = min(forecast_temps) if forecast_temps else 0
        else:
            data['forecast_temp_max'] = 0
            data['forecast_temp_min'] = 0

        # Debug: check if current_text is in data
        logger.info(f"Template data keys: {list(data.keys())}")
        logger.info(f"current_text value: '{data.get('current_text', 'KEY_NOT_FOUND')}'")

        return data, sunrise_dt, sunset_dt

    def map_qweather_icon(self, qweather_icon, display_style="default", is_day="1"):
        """
        Map QWeather icon codes to appropriate file paths based on display style and day/night.

        Args:
            qweather_icon: QWeather API icon code (e.g., "100", "101")
            display_style: Display style ("default", "nothing", "qweather")
            is_day: "1" for day, "0" for night

        Returns:
            Icon file path relative to plugin directory
        """
        # For qweather style, use QWeather official SVG icons directly
        if display_style == "qweather":
            # Convert day icon code to night icon code if needed
            if is_day == "0" and str(qweather_icon) in QWEATHER_DAY_TO_NIGHT:
                qweather_icon = QWEATHER_DAY_TO_NIGHT[str(qweather_icon)]
            return f"qweather/{qweather_icon}"

        # For nothing style, map to pixel icons
        if display_style == "nothing":
            # Convert day icon code to night icon code if needed
            if is_day == "0" and str(qweather_icon) in QWEATHER_DAY_TO_NIGHT:
                qweather_icon = QWEATHER_DAY_TO_NIGHT[str(qweather_icon)]

            # Map to OpenWeather-style codes first
            base_icon = QWEATHER_ICON_MAP.get(str(qweather_icon), "01d")

            # Only certain icons have day/night variants
            day_night_icons = ["01", "02", "10"]
            icon_code = base_icon[:2]

            # Apply night suffix if applicable
            if is_day == "0" and icon_code in day_night_icons:
                base_icon = icon_code + "n"

            pixel_icon_map = {
                "01d": "sun",     # 晴天 -> 太阳
                "01n": "moon",    # 晴夜 -> 月亮
                "02d": "k0",      # 少云 -> 太阳+云
                "02n": "l0",      # 少云夜 -> 月亮+云
                "03d": "Pf",      # 多云 -> 云
                "04d": "Hx",      # 阴天 -> 厚云
                "09d": "uu",      # 大雨 -> 云+大雨
                "10d": "xc",      # 雨 -> 云+雨
                "10n": "tc",      # 雨夜 -> 云+雨夜
                "11d": "gk",      # 雷暴 -> 云+闪电
                "13d": "nt",      # 雪 -> 云+雪
                "50d": "p8"       # 雾/霾 -> 雾
            }
            pixel_icon = pixel_icon_map.get(base_icon, "sun")
            return f"pixel/{pixel_icon}"

        # Default style uses OpenWeather-style mapping
        # Convert day icon code to night icon code if needed
        if is_day == "0" and str(qweather_icon) in QWEATHER_DAY_TO_NIGHT:
            qweather_icon = QWEATHER_DAY_TO_NIGHT[str(qweather_icon)]

        # Only certain icons have day/night variants
        day_night_icons = ["01", "02", "10"]
        icon_code = QWEATHER_ICON_MAP.get(str(qweather_icon), "01d")[:2]

        if is_day == "0" and icon_code in day_night_icons:
            return icon_code + "n"
        return icon_code + "d"

    def parse_forecast(self, daily_forecast, tz, language="zh", display_style="default", settings=None, air_quality=None, current_is_day="1"):
        forecast = []
        today = datetime.now(tz).date()

        for idx, day in enumerate(daily_forecast):
            dt = datetime.fromisoformat(day['fxDate']).replace(tzinfo=tz)

            # Skip dates before today
            if dt.date() < today:
                logger.debug(f"Skipping past date: {dt.date()}")
                continue

            # For today, use iconNight if current time is night, otherwise use iconDay
            # For other days, always use iconDay
            if dt.date() == today and current_is_day == "0":
                icon_code = day.get('iconNight', day.get('iconDay', '100'))
            else:
                icon_code = day.get('iconDay', '100')

            # Use current_is_day only for today, force day icon for all other days
            is_day_icon = current_is_day if dt.date() == today else "1"

            weather_icon = self.map_qweather_icon(icon_code, display_style, is_day_icon)

            # Handle icon for qweather style - Fixed path
            if display_style == "qweather":
                svg_path = self.get_plugin_dir(f'icons/{weather_icon}.svg')
                if os.path.exists(svg_path):
                    weather_icon_path = svg_path
                else:
                    # Fallback to PNG if SVG doesn't exist
                    weather_icon_path = self.get_plugin_dir(f"icons/{weather_icon}.png")
                    logger.warning(f"SVG icon not found: {svg_path}, using PNG fallback")
            else:
                weather_icon_path = self.get_plugin_dir(f"icons/{weather_icon}.png")

            weather_icon_code = weather_icon if display_style == "qweather" else ""

            if dt.date() == today:
                day_label = "今天" if language == "zh" else "Today"
            elif language == "zh":
                weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
                day_label = weekdays[dt.weekday()]
            else:
                day_label = dt.strftime("%a")

            target_date = dt.date()
            try:
                phase_age = moon.phase(target_date)
                phase_name = get_moon_phase_name(phase_age)
                LUNAR_CYCLE_DAYS = 29.530588853
                phase_fraction = phase_age / LUNAR_CYCLE_DAYS
                illum_pct = (1 - math.cos(2 * math.pi * phase_fraction)) / 2 * 100
            except Exception as e:
                logger.error(f"Error calculating moon phase for {target_date}: {e}")
                illum_pct = 0
                phase_name = "newmoon"

            # Moon phase or air quality display option (mutually exclusive)
            show_moon_phase = settings and settings.get('moonPhase') == "true"
            show_air_quality = settings and settings.get('showAirQuality') == "true"
            
            if show_moon_phase:
                # Handle moon phase icon for qweather style - Fixed path
                if display_style == "qweather":
                    # Check if we have SVG version of moon phase icon
                    svg_moon_path = self.get_plugin_dir(f'icons/{phase_name}.svg')
                    if os.path.exists(svg_moon_path):
                        moon_icon_path = svg_moon_path
                    else:
                        moon_icon_path = self.get_plugin_dir(f"icons/{phase_name}.png")
                else:
                    moon_icon_path = self.get_plugin_dir(f"icons/{phase_name}.png")
                moon_icon_code = phase_name if display_style == "qweather" else ""
                air_quality_display = None
            elif show_air_quality:
                # Generate air quality data for this day using actual current air quality
                air_quality_display = self.get_air_quality_for_forecast_day(day, tz, air_quality)
                moon_icon_path = None
                moon_icon_code = ""
            else:
                moon_icon_path = None
                moon_icon_code = ""
                air_quality_display = None

            forecast.append({
                "day": day_label,
                "high": int(float(day.get('tempMax', 0))),
                "low": int(float(day.get('tempMin', 0))),
                "icon": weather_icon_path,
                "icon_code": weather_icon_code,
                "moon_phase_pct": f"{illum_pct:.0f}",
                "moon_phase_icon": moon_icon_path,
                "moon_phase_icon_code": moon_icon_code,
                "air_quality_display": air_quality_display
            })

        return forecast

    def get_air_quality_for_forecast_day(self, forecast_day, tz, current_air_quality=None):
        """Generate air quality data for forecast days"""
        # For today, use actual current air quality if available
        today = datetime.now(tz).date()
        forecast_date = datetime.fromisoformat(forecast_day['fxDate']).replace(tzinfo=tz).date()
        
        if current_air_quality and forecast_date == today:
            # Use actual current air quality for today
            try:
                aqi_value = int(current_air_quality.get('aqi', 50))
                category = current_air_quality.get('category', '良')
            except (ValueError, TypeError):
                aqi_value = 50
                category = '良'
            
            # Map category to color - optimized for E6 with standard colors
            color_map = {
                '优': '#00CC00',      # Green - Excellent
                '良': '#CC9900',      # Dark yellow/mustard - Good
                '轻度污染': '#FF6600', # Orange - Light Pollution
                '中度污染': '#FF0000', # Pure red (E6) - Moderate Pollution
                '重度污染': '#9900CC', # Purple - Heavy Pollution
                '严重污染': '#990000'  # Dark red - Severe Pollution
            }
            color = color_map.get(category, '#CC9900')
        else:
            # For future days, use weather-based estimation
            import random
            
            # Weather-based air quality estimation
            weather_condition = forecast_day.get('iconDay', '100')
            wind_speed = float(forecast_day.get('windSpeedDay', '10'))
            
            # Base AQI on weather conditions
            if weather_condition in ['100', '101']:  # Clear/sunny
                base_aqi = random.randint(30, 70)  # Usually good to moderate
            elif weather_condition in ['300', '301', '302', '303', '304']:  # Rain
                base_aqi = random.randint(20, 50)  # Usually good after rain
            elif weather_condition in ['500', '501', '502', '503', '504']:  # Fog/haze
                base_aqi = random.randint(80, 150)  # Often moderate to unhealthy for sensitive
            else:  # Other conditions
                base_aqi = random.randint(40, 80)
            
            # Wind helps clear pollution
            if wind_speed > 15:
                base_aqi = max(20, base_aqi - 20)
            
            # Determine category and color - E6 standard colors for best visibility
            if base_aqi <= 50:
                category = "优"
                color = "#00CC00"  # Green
            elif base_aqi <= 100:
                category = "良"
                color = "#CC9900"  # Dark yellow/mustard
            elif base_aqi <= 150:
                category = "轻度污染"
                color = "#FF6600"  # Orange
            elif base_aqi <= 200:
                category = "中度污染"
                color = "#FF0000"  # Pure red (E6)
            elif base_aqi <= 300:
                category = "重度污染"
                color = "#9900CC"  # Purple
            else:
                category = "严重污染"
                color = "#990000"  # Dark red
            
        return {
            "category": category,
            "color": color,
            "text_color": "#FFFFFF",  # White text for all categories
            "rounded": "True"  # Use rounded corners to match forecast boxes
        }

    def parse_hourly(self, hourly_forecast, tz, time_format, units):
        hourly = []
        current_time = datetime.now(tz)

        for hour in hourly_forecast[:24]:
            dt = datetime.fromisoformat(hour['fxTime']).replace(tzinfo=tz)

            if dt < current_time:
                continue

            precip_prob = float(hour.get('pop', 0)) / 100.0
            precip_amount = float(hour.get('precip', 0))

            if units == "imperial":
                precip_amount = precip_amount / 25.4

            hour_forecast = {
                "time": self.format_time(dt, time_format, hour_only=True),
                "temperature": int(float(hour.get('temp', 0))),
                "precipitation": precip_prob,
                "rain": round(precip_amount, 2)
            }
            hourly.append(hour_forecast)

            if len(hourly) >= 24:
                break

        return hourly

    def get_minutely_data_with_hourly_temp(self, minutely_forecast, hourly_forecast, tz, time_format, units):
        """Get minutely precipitation data with temperature from hourly forecast"""
        if not minutely_forecast:
            return []
        
        current_time = datetime.now(tz)
        two_hours_later = current_time + timedelta(hours=2)
        
        # Build hourly temperature and precipitation probability map
        hourly_map = {}
        for hour in hourly_forecast:
            dt = datetime.fromisoformat(hour['fxTime']).replace(tzinfo=tz)
            hour_key = dt.strftime("%Y-%m-%d %H")
            hourly_map[hour_key] = {
                'temp': int(float(hour.get('temp', 0))),
                'pop': float(hour.get('pop', 0)) / 100.0,
                'time': dt.strftime("%H:%M")
            }
        
        # Get the first available hourly data as fallback
        first_hourly = None
        if hourly_forecast:
            first_hourly = {
                'temp': int(float(hourly_forecast[0].get('temp', 0))),
                'pop': float(hourly_forecast[0].get('pop', 0)) / 100.0
            }
        
        logger.info(f"Hourly data map: {hourly_map}")
        
        minutely_data = []
        for minute_data in minutely_forecast:
            dt = datetime.fromisoformat(minute_data['fxTime']).replace(tzinfo=tz)
            
            if dt < current_time:
                continue
            if dt > two_hours_later:
                break
                
            precip_amount = float(minute_data.get('precip', 0))
            if units == "imperial":
                precip_amount = precip_amount / 25.4
            
            # Only include if there's precipitation
            if precip_amount > 0:
                # Get temperature and pop from same hour in hourly forecast
                hour_key = dt.strftime("%Y-%m-%d %H")
                hourly_data = hourly_map.get(hour_key)
                
                # If current hour's data not available, use first available hourly data
                if hourly_data is None and first_hourly is not None:
                    temperature = first_hourly['temp']
                    precipitation_prob = first_hourly['pop']
                elif hourly_data is not None:
                    temperature = hourly_data['temp']
                    precipitation_prob = hourly_data['pop']
                else:
                    temperature = 0
                    precipitation_prob = 1.0
                
                minutely_item = {
                    "time": self.format_time(dt, time_format, hour_only=False),
                    "temperature": temperature,
                    "precipitation": precipitation_prob,
                    "rain": round(precip_amount, 2)
                }
                minutely_data.append(minutely_item)
                logger.info(f"Minutely: {dt.strftime('%H:%M')} temp={temperature}°C pop={precipitation_prob*100:.0f}% rain={precip_amount:.2f}mm")
        
        return minutely_data

    def parse_hourly_forecast(self, hourly_forecast, tz, time_format, units, current_weather=None, display_style="default"):
        """Parse hourly forecast data without minutely merging"""
        current_time = datetime.now(tz)
        hourly_data = []

        # Add current weather as the first data point if available
        if current_weather:
            current_temp = int(float(current_weather.get('temp', 0)))
            # Use first hour's precipitation data as fallback for current
            first_hour_precip = 0
            first_hour_pop = 0
            current_icon_code = current_weather.get('icon', '100')
            if hourly_forecast and len(hourly_forecast) > 0:
                first_hour_precip = float(hourly_forecast[0].get('precip', 0))
                first_hour_pop = float(hourly_forecast[0].get('pop', 0)) / 100.0
                if units == "imperial":
                    first_hour_precip = first_hour_precip / 25.4

            current_item = {
                "time": self.format_time(current_time, time_format, hour_only=True),
                "time_full": current_time.strftime("%H:%M"),
                "hour": current_time.hour,
                "temperature": current_temp,
                "precipitation": first_hour_pop,
                "rain": round(first_hour_precip, 2),
                "icon": self.get_plugin_dir(f"icons/{self.map_qweather_icon(current_icon_code, display_style, '1')}.png")
            }
            hourly_data.append(current_item)
            logger.info(f"Current: {current_time.strftime('%H:%M')} temp={current_temp}°C")

        for hour in hourly_forecast:
            dt = datetime.fromisoformat(hour['fxTime']).replace(tzinfo=tz)

            if dt <= current_time:
                continue

            precip_prob = float(hour.get('pop', 0)) / 100.0
            precip_amount = float(hour.get('precip', 0))
            if units == "imperial":
                precip_amount = precip_amount / 25.4

            # Get weather icon
            icon_code = hour.get('icon', '100')
            is_day = '1' if 6 <= dt.hour < 18 else '0'  # Simple day/night detection
            weather_icon = self.map_qweather_icon(icon_code, display_style, is_day)

            # Handle icon for qweather style - use SVG, otherwise PNG
            if display_style == "qweather":
                svg_path = self.get_plugin_dir(f'icons/{weather_icon}.svg')
                if os.path.exists(svg_path):
                    icon_path = svg_path
                else:
                    # Fallback to PNG if SVG doesn't exist
                    icon_path = self.get_plugin_dir(f"icons/{weather_icon}.png")
            else:
                icon_path = self.get_plugin_dir(f"icons/{weather_icon}.png")

            hour_item = {
                "time": self.format_time(dt, time_format, hour_only=True),
                "time_full": dt.strftime("%H:%M"),
                "hour": dt.hour,
                "temperature": int(float(hour.get('temp', 0))),
                "precipitation": precip_prob,
                "rain": round(precip_amount, 2),
                "icon": icon_path
            }
            hourly_data.append(hour_item)
            logger.info(f"Hourly: {dt.strftime('%H:%M')} temp={hour_item['temperature']}°C pop={precip_prob*100:.0f}% rain={precip_amount:.2f}mm icon={icon_code}")

            if len(hourly_data) >= 24:
                break

        hourly_data = hourly_data[:24]

        # Smooth the precipitation probability with a 3-hour moving average
        # for display: raw hourly values zigzag (e.g. 30/70/35/60%) and the
        # bar chart looks jittery next to the smooth temperature line.
        probs = [h["precipitation"] for h in hourly_data]
        for i, h in enumerate(hourly_data):
            lo, hi = max(0, i - 1), min(len(probs), i + 2)
            h["precipitation"] = round(sum(probs[lo:hi]) / (hi - lo), 3)

        return hourly_data

    def merge_minutely_and_hourly(self, minutely_forecast, hourly_forecast, tz, time_format, units, display_style="default"):
        """Merge minutely precipitation into hourly data: keep hourly temperature, replace precipitation for covered hours"""
        current_time = datetime.now(tz)

        # Build minutely precipitation map by time
        minutely_map = {}
        if minutely_forecast:
            for minute_data in minutely_forecast:
                dt = datetime.fromisoformat(minute_data['fxTime']).replace(tzinfo=tz)
                if dt < current_time:
                    continue

                precip_amount = float(minute_data.get('precip', 0))
                if units == "imperial":
                    precip_amount = precip_amount / 25.4

                # Store precipitation data for each minute
                time_key = dt.strftime("%Y-%m-%d %H:%M")
                minutely_map[time_key] = {
                    'precip': precip_amount,
                    'dt': dt
                }

        logger.info(f"Minutely data points: {len(minutely_map)}")

        # Process hourly data
        merged = []
        for hour in hourly_forecast:
            dt = datetime.fromisoformat(hour['fxTime']).replace(tzinfo=tz)

            if dt < current_time:
                continue

            hour_key = dt.strftime("%Y-%m-%d %H")

            # Check if this hour has minutely precipitation data
            has_minutely = False
            minutely_precip = 0

            for time_key, minute_data in minutely_map.items():
                if time_key.startswith(hour_key):
                    has_minutely = True
                    # Use the maximum precipitation in this hour
                    minutely_precip = max(minutely_precip, minute_data['precip'])

            # Use hourly temperature and pop
            precip_prob = float(hour.get('pop', 0)) / 100.0
            temperature = int(float(hour.get('temp', 0)))

            # If has minutely data, use minutely precipitation amount; otherwise use hourly
            if has_minutely:
                precip_amount = minutely_precip
                logger.info(f"Hour {dt.strftime('%H:%M')} using minutely precip: {precip_amount:.2f}mm")
            else:
                precip_amount = float(hour.get('precip', 0))
                if units == "imperial":
                    precip_amount = precip_amount / 25.4

            # Get weather icon
            icon_code = hour.get('icon', '100')
            is_day = '1' if 6 <= dt.hour < 18 else '0'  # Simple day/night detection
            weather_icon = self.map_qweather_icon(icon_code, display_style, is_day)

            # Handle icon for qweather style - use SVG, otherwise PNG
            if display_style == "qweather":
                svg_path = self.get_plugin_dir(f'icons/{weather_icon}.svg')
                if os.path.exists(svg_path):
                    icon_path = svg_path
                else:
                    # Fallback to PNG if SVG doesn't exist
                    icon_path = self.get_plugin_dir(f"icons/{weather_icon}.png")
            else:
                icon_path = self.get_plugin_dir(f"icons/{weather_icon}.png")

            hour_item = {
                "time": self.format_time(dt, time_format, hour_only=True),
                "time_full": dt.strftime("%H:%M"),
                "hour": dt.hour,
                "temperature": temperature,
                "precipitation": precip_prob,
                "rain": round(precip_amount, 2),
                "icon": icon_path
            }
            merged.append(hour_item)
            logger.info(f"Merged: {dt.strftime('%H:%M')} temp={temperature}°C pop={precip_prob*100:.0f}% rain={precip_amount:.2f}mm icon={icon_code}")

            if len(merged) >= 24:
                break

        return merged[:24]

    def parse_data_points(self, current_weather, today_forecast, air_quality, tz, units, time_format, language="zh", display_style="default"):
        data_points = []
        sunrise_dt = None
        sunset_dt = None

        logger.info(f"parse_data_points called with display_style: {display_style}")

        # Get current time for timezone debugging
        now = datetime.now(tz)
        logger.info(f"Current time in timezone {tz}: {now}")

        sunrise_str = today_forecast.get('sunrise')
        if sunrise_str:
            naive_sunrise = datetime.strptime(sunrise_str, "%H:%M").replace(
                year=now.year,
                month=now.month,
                day=now.day
            )
            sunrise_dt = tz.localize(naive_sunrise)
            logger.debug(f"Sunrise time: {sunrise_dt}")
            data_points.append({
                "label": LABELS[language]["sunrise"],
                "measurement": self.format_time(sunrise_dt, time_format, include_am_pm=False),
                "unit": "" if time_format == "24h" else sunrise_dt.strftime('%p'),
                "icon": self.get_plugin_dir('icons/sunrise.png')
            })

        sunset_str = today_forecast.get('sunset')
        if sunset_str:
            naive_sunset = datetime.strptime(sunset_str, "%H:%M").replace(
                year=now.year,
                month=now.month,
                day=now.day
            )
            sunset_dt = tz.localize(naive_sunset)
            logger.debug(f"Sunset time: {sunset_dt}")
            data_points.append({
                "label": LABELS[language]["sunset"],
                "measurement": self.format_time(sunset_dt, time_format, include_am_pm=False),
                "unit": "" if time_format == "24h" else sunset_dt.strftime('%p'),
                "icon": self.get_plugin_dir('icons/sunset.png')
            })

        # Wind - label shows "WindDir Level", measurement shows speed
        wind_dir_text = current_weather.get('windDir', '')  # 风向文字（如"西风"）
        wind_scale = current_weather.get('windScale', '0')  # 风力等级（如"2"）
        wind_speed = current_weather.get('windSpeed', '0')  # 风速数值
        wind_dir_360 = current_weather.get('wind360', '0')
        wind_arrow = self.get_wind_arrow(float(wind_dir_360) if wind_dir_360 else 0)

        # Format: label="西风 2级", measurement=wind_speed, unit=km/h
        if language == "zh":
            wind_label = f"{wind_dir_text} {wind_scale}级"  # "西风 2级"
        else:
            wind_label = f"{wind_dir_text} Level {wind_scale}"  # "West Level 2"

        data_points.append({
            "label": wind_label,
            "measurement": wind_speed,
            "unit": UNITS[units]["speed"],
            "icon": self.get_plugin_dir('icons/wind.png'),
            "arrow": wind_arrow
        })

        humidity = current_weather.get('humidity', '0')
        data_points.append({
            "label": LABELS[language]["humidity"],
            "measurement": humidity,
            "unit": '%',
            "icon": self.get_plugin_dir('icons/humidity.png')
        })

        pressure = current_weather.get('pressure', '0')
        data_points.append({
            "label": LABELS[language]["pressure"],
            "measurement": pressure,
            "unit": 'hPa',
            "icon": self.get_plugin_dir('icons/pressure.png')
        })

        uv_index = today_forecast.get('uvIndex', '0')
        data_points.append({
            "label": LABELS[language]["uv_index"],
            "measurement": uv_index,
            "unit": '',
            "icon": self.get_plugin_dir('icons/uvi.png')
        })

        visibility = float(current_weather.get('vis', '10'))
        visibility_str = f">{visibility}" if visibility >= 10 else visibility
        data_points.append({
            "label": LABELS[language]["visibility"],
            "measurement": visibility_str,
            "unit": 'km',
            "icon": self.get_plugin_dir('icons/visibility.png')
        })

        if air_quality:
            aqi = air_quality.get('aqi', 'N/A')
            aqi_category = air_quality.get('category', '')
            aqi_color = self.get_aqi_color(aqi) if aqi != 'N/A' else None
            # Use the new air-quality.png icon for qweather style
            aqi_icon_path = self.get_plugin_dir('icons/air-quality.png') if display_style == "qweather" else self.get_plugin_dir('icons/aqi.png')

            # Format: label="空气质量 优"
            aqi_label = f"{LABELS[language]['air_quality']} {aqi_category}" if aqi_category else LABELS[language]["air_quality"]

            data_points.append({
                "label": aqi_label,  # "空气质量 优"
                "measurement": aqi,  # AQI数值
                "unit": "",
                "icon": aqi_icon_path,
                "aqi_color": aqi_color
            })

        return data_points, sunrise_dt, sunset_dt

    def get_aqi_color(self, aqi_value):
        """Return color based on AQI value - optimized for E6 display"""
        if aqi_value == 'N/A':
            return None

        try:
            aqi = int(aqi_value)
        except (ValueError, TypeError):
            return None

        # AQI color standards - optimized for E6 display
        if aqi <= 50:
            return "#00CC00"  # Green - Excellent
        elif aqi <= 100:
            return "#CC9900"  # Dark yellow/mustard - Good
        elif aqi <= 150:
            return "#FF6600"  # Orange - Light Pollution
        elif aqi <= 200:
            return "#FF0000"  # Pure red (E6) - Moderate Pollution
        elif aqi <= 300:
            return "#9900CC"  # Purple - Heavy Pollution
        else:
            return "#990000"  # Dark red - Severe Pollution

    def format_time(self, dt, time_format, hour_only=False, include_am_pm=True):
        if time_format == "24h":
            return dt.strftime("%H:00" if hour_only else "%H:%M")

        if include_am_pm:
            fmt = "%I %p" if hour_only else "%I:%M %p"
        else:
            fmt = "%I" if hour_only else "%I:%M"

        return dt.strftime(fmt).lstrip("0")

    def get_wind_arrow(self, wind_deg: float) -> str:
        """Get wind direction arrow based on wind degrees.
        Arrow points DOWN (toward) the wind source, not where it's going."""
        DIRECTIONS = [
            ("↓", 22.5),    # North (N) - wind from north
            ("↙", 67.5),    # North-East (NE)
            ("←", 112.5),   # East (E)
            ("↖", 157.5),   # South-East (SE)
            ("↑", 202.5),   # South (S)
            ("↗", 247.5),   # South-West (SW)
            ("→", 292.5),   # West (W)
            ("↘", 337.5),   # North-West (NW)
            ("↓", 360.0)    # Wrap back to North
        ]
        wind_deg = wind_deg % 360
        for arrow, upper_bound in DIRECTIONS:
            if wind_deg < upper_bound:
                return arrow

        return "↓"

    def determine_theme(self, theme_mode, sunrise_dt, sunset_dt, tz):
        """
        Determine theme mode based on settings and sunrise/sunset time.

        Args:
            theme_mode: "light", "dark", or "auto"
            sunrise_dt: Sunrise datetime
            sunset_dt: Sunset datetime
            tz: Timezone

        Returns:
            True for dark mode, False for light mode
        """
        logger.info(f"determine_theme called with theme_mode: {theme_mode}")

        if sunrise_dt and sunset_dt:
            now = datetime.now(tz)
            logger.debug(f"Current time: {now}, Sunrise: {sunrise_dt}, Sunset: {sunset_dt}")
        else:
            logger.info(f"Missing sunrise/sunset times")

        if theme_mode == "light":
            logger.info("Theme mode set to light")
            return False
        elif theme_mode == "dark":
            logger.info("Theme mode set to dark")
            return True
        elif theme_mode == "auto":
            if sunrise_dt and sunset_dt:
                now = datetime.now(tz)
                # Transition to day mode 30 minutes before sunrise (sky starts getting brighter)
                sunrise_transition = sunrise_dt - timedelta(minutes=30)
                result = now < sunrise_transition or now >= sunset_dt
                logger.debug(f"Auto theme result: {result} (current time: {now}, sunrise transition: {sunrise_transition}, sunset: {sunset_dt})")
                return result
            logger.warning("Auto theme mode but no sunrise/sunset data, defaulting to light")
            return False
        logger.warning(f"Unknown theme mode: {theme_mode}, defaulting to light")
        return False

    def parse_weather_alerts(self, alerts, language="zh"):
        logger.info(f"Parsing weather alerts: {len(alerts) if alerts else 0} alert(s)")
        if not alerts:
            logger.info("No weather alerts to parse")
            return []

        severity_colors = {
            "extreme": {"bg": "#FF0000", "text": "#FFFFFF"},     # Pure red (E6) - 极端/红色预警
            "severe": {"bg": "#FF4500", "text": "#FFFFFF"},      # Orange-red - 严重/橙色预警
            "moderate": {"bg": "#FFFF00", "text": "#000000"},     # Pure yellow (E6) - 中等/黄色预警
            "minor": {"bg": "#0000FF", "text": "#FFFFFF"},        # Pure blue (E6) - 轻微/蓝色预警
            "unknown": {"bg": "#0000FF", "text": "#FFFFFF"}       # Pure blue (E6) - 未知/默认
        }

        # Use a dictionary to deduplicate alerts by headline (severity + type)
        # Keep the most recent one (latest issued time)
        unique_alerts = {}
        for alert in alerts:
            event_name = alert.get('eventType', {}).get('name', '')
            headline = alert.get('headline', event_name)
            description = alert.get('description', '')

            # Filter out alerts with "解除" (cancelled/lifted) in headline or description
            if headline and '解除' in headline:
                logger.info(f"Skipping cancelled alert: {headline}")
                continue
            if description and '解除' in description:
                logger.info(f"Skipping cancelled alert with description containing '解除': {headline}")
                continue

            severity = alert.get('severity', 'minor')
            colors = severity_colors.get(severity, severity_colors['minor'])

            # Simplify headline by removing weather station prefix
            if headline:
                import re
                # Match everything before "发布" and remove it
                headline = re.sub(r'.*?发布', '', headline)
                # Remove "信号" suffix
                headline = re.sub(r'信号$', '', headline)
                headline = headline.strip()
                if not headline and event_name:
                    headline = event_name

            # Derive a short headline (alert type + level, e.g. "雷电黄色预警")
            # so the header badge stays compact and never crowds out the date
            short_headline = headline
            for sep in ('：', ':'):
                if sep in headline:
                    short_headline = headline.split(sep)[0].strip()
                    break
            short_headline = re.sub(r'信号$', '', short_headline).strip() or headline

            if language == "en" and not headline:
                headline = alert.get('eventType', {}).get('code', 'Weather Alert')

            # Use headline as key to deduplicate
            if headline not in unique_alerts:
                unique_alerts[headline] = {
                    'headline': headline,
                    'short_headline': short_headline or headline,
                    'description': description[:200] if description else '',
                    'severity': severity,
                    'bg_color': colors['bg'],
                    'text_color': colors['text'],
                    'issued_time': alert.get('issuedTime', ''),
                    'expire_time': alert.get('expireTime', '')
                }
            else:
                # Update with latest issued time if this one is more recent
                existing_issued = unique_alerts[headline]['issued_time']
                new_issued = alert.get('issuedTime', '')
                if new_issued > existing_issued:
                    unique_alerts[headline]['issued_time'] = new_issued
                    unique_alerts[headline]['expire_time'] = alert.get('expireTime', '')

        # Most severe first (red > orange > yellow > blue), then fill the 2x2
        # badge grid: top 3 alerts + a "+N条预警" counter badge if truncated,
        # so nothing important is silently dropped
        severity_rank = {"extreme": 0, "severe": 1, "moderate": 2, "minor": 3}
        all_alerts = sorted(unique_alerts.values(),
                            key=lambda a: severity_rank.get(a['severity'], 4))

        if len(all_alerts) > 4:
            hidden = len(all_alerts) - 3
            parsed_alerts = all_alerts[:3] + [{
                'headline': f'+{hidden}条预警',
                'short_headline': f'+{hidden}条预警',
                'description': '',
                'severity': 'minor',
                'bg_color': '#000000',
                'text_color': '#FFFFFF',
                'issued_time': '',
                'expire_time': ''
            }]
        else:
            parsed_alerts = all_alerts[:4]

        logger.info(f"Parsed {len(parsed_alerts)} weather alert(s): {parsed_alerts}")
        return parsed_alerts
