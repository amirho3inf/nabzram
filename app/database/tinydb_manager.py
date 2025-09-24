"""
TinyDB database manager for persistent storage
"""

import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from tinydb import Query, TinyDB
from tinydb.middlewares import CachingMiddleware
from tinydb.storages import JSONStorage

from app.models.database import ServerModel, SettingsModel, SubscriptionModel


class DatabaseManager:
    """Manages TinyDB operations for subscriptions, servers, and settings"""

    def __init__(self, db_path: str = "data/db.json"):
        """Initialize the database manager"""
        self.db_path = db_path

        # Ensure database directory exists
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

        # Initialize TinyDB with caching middleware for better performance
        self.db = TinyDB(db_path, storage=CachingMiddleware(JSONStorage), indent=2)

        # Get tables
        self.subscriptions_table = self.db.table("subscriptions")
        self.settings_table = self.db.table("settings")

        # Initialize settings if not exists
        self._init_settings()

    def _init_settings(self):
        """Initialize default settings if they don't exist"""
        if not self.settings_table.all():
            default_settings = SettingsModel(
                xray_binary="xray",  # Default xray binary name
                xray_assets_folder=None,  # No default assets folder
                xray_log_level="warning",  # Default log level
            )
            self.settings_table.insert(default_settings.model_dump())

    def _serialize_for_db(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Serialize data for database storage"""
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                if isinstance(value, UUID):
                    result[key] = str(value)
                elif isinstance(value, datetime):
                    result[key] = value.isoformat()
                elif isinstance(value, dict):
                    result[key] = self._serialize_for_db(value)
                elif isinstance(value, list):
                    result[key] = [
                        self._serialize_for_db(item) if isinstance(item, dict) else item
                        for item in value
                    ]
                else:
                    result[key] = value
            return result
        return data

    def _deserialize_from_db(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Deserialize data from database storage"""
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                if key in ["id"] and isinstance(value, str):
                    try:
                        result[key] = UUID(value)
                    except ValueError:
                        result[key] = value
                elif key in ["last_updated"] and isinstance(value, str):
                    try:
                        result[key] = datetime.fromisoformat(value)
                    except ValueError:
                        result[key] = None
                elif key == "user_info" and isinstance(value, dict):
                    # Handle nested datetime in user_info.expire
                    user_info_data = self._deserialize_from_db(value)
                    if "expire" in user_info_data and isinstance(
                        user_info_data["expire"], str
                    ):
                        try:
                            user_info_data["expire"] = datetime.fromisoformat(
                                user_info_data["expire"]
                            )
                        except ValueError:
                            user_info_data["expire"] = None
                    result[key] = user_info_data
                elif isinstance(value, dict):
                    result[key] = self._deserialize_from_db(value)
                elif isinstance(value, list):
                    result[key] = [
                        self._deserialize_from_db(item)
                        if isinstance(item, dict)
                        else item
                        for item in value
                    ]
                else:
                    result[key] = value
            return result
        return data

    # Subscription operations
    def create_subscription(self, subscription: SubscriptionModel) -> SubscriptionModel:
        """Create a new subscription"""
        data = self._serialize_for_db(subscription.model_dump())
        self.subscriptions_table.insert(data)
        return subscription

    def get_subscription(self, subscription_id: UUID) -> Optional[SubscriptionModel]:
        """Get a subscription by ID"""
        query = Query()
        result = self.subscriptions_table.search(query.id == str(subscription_id))
        if result:
            data = self._deserialize_from_db(result[0])
            return SubscriptionModel(**data)
        return None

    def get_all_subscriptions(self) -> List[SubscriptionModel]:
        """Get all subscriptions"""
        results = self.subscriptions_table.all()
        subscriptions = []
        for result in results:
            data = self._deserialize_from_db(result)
            subscriptions.append(SubscriptionModel(**data))
        return subscriptions

    def update_subscription(
        self, subscription_id: UUID, updates: Dict[str, Any]
    ) -> Optional[SubscriptionModel]:
        """Update a subscription"""
        query = Query()
        serialized_updates = self._serialize_for_db(updates)

        # Add last_updated timestamp
        if "last_updated" not in serialized_updates:
            serialized_updates["last_updated"] = datetime.now().isoformat()

        self.subscriptions_table.update(
            serialized_updates, query.id == str(subscription_id)
        )
        return self.get_subscription(subscription_id)

    def delete_subscription(self, subscription_id: UUID) -> bool:
        """Delete a subscription"""
        query = Query()
        result = self.subscriptions_table.remove(query.id == str(subscription_id))
        return len(result) > 0

    def update_subscription_servers(
        self, subscription_id: UUID, servers: List[ServerModel]
    ) -> Optional[SubscriptionModel]:
        """Update servers for a subscription"""
        serialized_servers = [
            self._serialize_for_db(server.model_dump()) for server in servers
        ]
        updates = {
            "servers": serialized_servers,
            "last_updated": datetime.now().isoformat(),
        }
        return self.update_subscription(subscription_id, updates)

    def update_subscription_with_user_info(
        self, subscription_id: UUID, servers: List[ServerModel], user_info
    ) -> Optional[SubscriptionModel]:
        """Update servers and user info for a subscription"""
        serialized_servers = [
            self._serialize_for_db(server.model_dump()) for server in servers
        ]
        updates = {
            "servers": serialized_servers,
            "last_updated": datetime.now().isoformat(),
        }

        # Add user_info if provided
        if user_info:
            updates["user_info"] = self._serialize_for_db(user_info.model_dump())

        return self.update_subscription(subscription_id, updates)

    # Server operations (within subscriptions)
    def get_server(
        self, subscription_id: UUID, server_id: UUID
    ) -> Optional[ServerModel]:
        """Get a server by ID within a subscription"""
        subscription = self.get_subscription(subscription_id)
        if subscription:
            for server in subscription.servers:
                if server.id == server_id:
                    return server
        return None

    def update_server_status(
        self, subscription_id: UUID, server_id: UUID, status: str
    ) -> Optional[ServerModel]:
        """Update server status"""
        subscription = self.get_subscription(subscription_id)
        if subscription:
            for i, server in enumerate(subscription.servers):
                if server.id == server_id:
                    subscription.servers[i].status = status
                    self.update_subscription_servers(
                        subscription_id, subscription.servers
                    )
                    return subscription.servers[i]
        return None

    # Settings operations
    def get_settings(self) -> SettingsModel:
        """Get current settings"""
        result = self.settings_table.all()
        if result:
            return SettingsModel(**result[0])
        return SettingsModel()

    def update_settings(self, settings: SettingsModel) -> SettingsModel:
        """Update settings"""
        data = settings.model_dump()
        self.settings_table.truncate()  # Clear existing settings
        self.settings_table.insert(data)
        return settings

    def close(self):
        """Close the database connection"""
        self.db.close()
