"""Settings service for database-backed configuration management."""

import json
from typing import Any, Dict
from sqlalchemy.orm import Session
from ..models import Setting
from datetime import datetime, timezone


class SettingsService:
    """Service for managing application settings in the database.

    Provides type-safe get/set operations with automatic type conversion.
    Replaces: load_settings/save_settings functions in web_app.py
    """

    def __init__(self, db: Session):
        self.db = db

    def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value with type conversion.

        Args:
            key: Setting key
            default: Default value if key doesn't exist

        Returns:
            Setting value converted to appropriate type, or default
        """
        setting = self.db.query(Setting).filter(Setting.key == key).first()
        if not setting:
            return default

        # Convert from stored string to actual type
        value_type = setting.value_type
        value = setting.value

        if value_type == "bool":
            return value.lower() in ("true", "1", "yes", "on")
        elif value_type == "int":
            return int(value)
        elif value_type == "float":
            return float(value)
        elif value_type == "json":
            return json.loads(value)
        else:  # string
            return value

    def set(self, key: str, value: Any) -> None:
        """Set a setting value with automatic type detection.

        Args:
            key: Setting key
            value: Setting value (any JSON-serializable type)
        """
        # Determine type and convert to string for storage
        if isinstance(value, bool):
            value_type = "bool"
            value_str = str(value).lower()
        elif isinstance(value, int):
            value_type = "int"
            value_str = str(value)
        elif isinstance(value, float):
            value_type = "float"
            value_str = str(value)
        elif isinstance(value, (dict, list)):
            value_type = "json"
            value_str = json.dumps(value)
        else:
            value_type = "string"
            value_str = str(value)

        # Update or create setting
        setting = self.db.query(Setting).filter(Setting.key == key).first()
        if setting:
            setting.value = value_str
            setting.value_type = value_type
            setting.updated_at = datetime.now(timezone.utc)
        else:
            setting = Setting(
                key=key,
                value=value_str,
                value_type=value_type,
                updated_at=datetime.now(timezone.utc),
            )
            self.db.add(setting)

        try:
            self.db.commit()
        except Exception as e:
            error_msg = str(e).lower()
            if "no transaction" in error_msg:
                pass
            else:
                try:
                    self.db.rollback()
                except Exception:
                    pass  # Rollback itself may fail if no transaction
                raise

    def get_all(self) -> Dict[str, Any]:
        """Get all settings as a dictionary.

        Returns:
            Dictionary of all settings with type conversion applied
        """
        settings = self.db.query(Setting).all()
        result = {}
        for setting in settings:
            # Use get() method to apply type conversion
            result[setting.key] = self.get(setting.key)
        return result

    def set_many(self, settings: Dict[str, Any]) -> None:
        """Set multiple settings at once.

        Args:
            settings: Dictionary of key-value pairs to set
        """
        for key, value in settings.items():
            self.set(key, value)

    def delete(self, key: str) -> bool:
        """Delete a setting.

        Args:
            key: Setting key to delete

        Returns:
            True if setting was deleted, False if it didn't exist
        """
        setting = self.db.query(Setting).filter(Setting.key == key).first()
        if setting:
            self.db.delete(setting)
            try:
                self.db.commit()
            except Exception as e:
                error_msg = str(e).lower()
                if "no transaction" in error_msg:
                    pass
                else:
                    try:
                        self.db.rollback()
                    except Exception:
                        pass  # Rollback itself may fail if no transaction
                    raise
            return True
        return False

    def initialize_defaults(self, defaults: Dict[str, Any]) -> None:
        """Initialize settings with default values if they don't exist.

        Args:
            defaults: Dictionary of default key-value pairs
        """
        for key, value in defaults.items():
            existing = self.db.query(Setting).filter(Setting.key == key).first()
            if not existing:
                self.set(key, value)
