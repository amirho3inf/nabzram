"""
Settings management API routes
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.database.tinydb_manager import DatabaseManager
from app.dependencies import get_database
from app.models.database import SettingsModel
from app.models.schemas import SettingsResponse, SettingsUpdate, SettingsUpdateResponse
from app.services.process_service import process_manager

router = APIRouter()
logger = logging.getLogger(__name__)


async def restart_current_server_if_running():
    """Restart the currently running server if any"""
    try:
        if process_manager.current_server_id and process_manager.is_server_running(
            process_manager.current_server_id
        ):
            logger.info(
                f"Restarting server {process_manager.current_server_id} after settings update"
            )

            # Get the current server info to restart it with the same configuration
            server_info = process_manager.running_processes.get(
                process_manager.current_server_id
            )
            if server_info:
                # Stop the current server
                await process_manager.stop_server(process_manager.current_server_id)

                # Restart with the same configuration
                success, error_msg = await process_manager.start_single_server(
                    server_info.server_id,
                    server_info.subscription_id,
                    server_info.config,
                )

                if success:
                    logger.info(
                        f"Successfully restarted server {process_manager.current_server_id}"
                    )
                    return True
                else:
                    logger.error(
                        f"Failed to restart server {process_manager.current_server_id}: {error_msg}"
                    )
                    return False
            else:
                logger.warning(
                    f"Could not find server info for {process_manager.current_server_id}"
                )
        return False
    except Exception as e:
        logger.error(f"Failed to restart server: {e}")
        return False


@router.get("", response_model=SettingsResponse)
async def get_settings(db: DatabaseManager = Depends(get_database)):
    """Get current global settings"""
    try:
        settings = db.get_settings()

        return SettingsResponse(
            socks_port=settings.socks_port,
            http_port=settings.http_port,
            xray_binary=settings.xray_binary,
            xray_assets_folder=settings.xray_assets_folder,
            xray_log_level=settings.xray_log_level,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.put("", response_model=SettingsUpdateResponse)
async def update_settings(
    settings_update: SettingsUpdate, db: DatabaseManager = Depends(get_database)
):
    """Update global settings (e.g., change default SOCKS/HTTP ports)"""
    try:
        # Get current settings
        current_settings = db.get_settings()

        # Create updated settings
        updated_settings = SettingsModel(
            socks_port=settings_update.socks_port
            if settings_update.socks_port is not None
            else current_settings.socks_port,
            http_port=settings_update.http_port
            if settings_update.http_port is not None
            else current_settings.http_port,
            xray_binary=settings_update.xray_binary
            if settings_update.xray_binary is not None
            else current_settings.xray_binary,
            xray_assets_folder=settings_update.xray_assets_folder
            if settings_update.xray_assets_folder is not None
            else current_settings.xray_assets_folder,
            xray_log_level=settings_update.xray_log_level
            if settings_update.xray_log_level is not None
            else current_settings.xray_log_level,
        )

        # Validate port ranges
        if updated_settings.socks_port is not None:
            if not (1 <= updated_settings.socks_port <= 65535):
                raise HTTPException(
                    status_code=400, detail="SOCKS port must be between 1 and 65535"
                )

        if updated_settings.http_port is not None:
            if not (1 <= updated_settings.http_port <= 65535):
                raise HTTPException(
                    status_code=400, detail="HTTP port must be between 1 and 65535"
                )

        # Check for port conflicts
        if (
            updated_settings.socks_port is not None
            and updated_settings.http_port is not None
            and updated_settings.socks_port == updated_settings.http_port
        ):
            raise HTTPException(
                status_code=400, detail="SOCKS and HTTP ports cannot be the same"
            )

        # Validate log level
        if updated_settings.xray_log_level is not None:
            valid_log_levels = ["debug", "info", "warning", "error", "none"]
            if updated_settings.xray_log_level not in valid_log_levels:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid log level. Must be one of: {', '.join(valid_log_levels)}",
                )

        # Save updated settings
        db.update_settings(updated_settings)

        # Check if xray-related settings were changed (requires server restart)
        xray_settings_changed = (
            settings_update.xray_binary is not None
            or settings_update.xray_assets_folder is not None
            or settings_update.xray_log_level is not None
        )

        # Prepare response message
        changes = []
        if settings_update.socks_port is not None:
            changes.append(f"SOCKS port: {settings_update.socks_port}")
        if settings_update.http_port is not None:
            changes.append(f"HTTP port: {settings_update.http_port}")
        if settings_update.xray_binary is not None:
            changes.append(f"Xray binary: {settings_update.xray_binary}")
        if settings_update.xray_assets_folder is not None:
            changes.append(f"Xray assets folder: {settings_update.xray_assets_folder}")
        if settings_update.xray_log_level is not None:
            changes.append(f"Xray log level: {settings_update.xray_log_level}")

        message = f"Settings updated successfully: {', '.join(changes)}"

        # Restart server if xray settings changed
        if xray_settings_changed:
            restarted = await restart_current_server_if_running()
            if restarted:
                message += " and restarted the running server"

        return SettingsUpdateResponse(
            success=True,
            message=message,
            socks_port=updated_settings.socks_port,
            http_port=updated_settings.http_port,
            xray_binary=updated_settings.xray_binary,
            xray_assets_folder=updated_settings.xray_assets_folder,
            xray_log_level=updated_settings.xray_log_level,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
