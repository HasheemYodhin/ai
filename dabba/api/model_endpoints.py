"""
Model management API endpoints.

Provides GET /v1/models for listing available models, following the
OpenAI API format for model discovery.
"""

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from dabba.api.openai_compat import ModelInfo, ModelList


def create_model_router(
    available_models: Optional[List[str]] = None,
    auth: Optional[object] = None,
) -> APIRouter:
    """
    Create a FastAPI router for model management endpoints.

    Args:
        available_models: List of available model names.
        auth: Optional authentication dependency.

    Returns:
        Configured FastAPI APIRouter.
    """
    router = APIRouter(prefix="/v1", tags=["models"])
    models = available_models or ["dabba"]

    @router.get("/models")
    async def list_models():
        """
        List all available models.

        Returns a list of model objects in OpenAI-compatible format.
        """
        model_list = ModelList(
            data=[
                ModelInfo(id=name, owned_by="dabba")
                for name in models
            ]
        )
        return model_list.to_dict()

    @router.get("/models/{model_name}")
    async def get_model(model_name: str):
        """
        Get information about a specific model.

        Args:
            model_name: Name of the model to retrieve.

        Returns:
            Model information object.

        Raises:
            HTTPException: If the model is not found.
        """
        if model_name not in models:
            raise HTTPException(
                status_code=404,
                detail=f"Model '{model_name}' not found",
            )

        model_info = ModelInfo(id=model_name, owned_by="dabba")
        return {
            "id": model_info.id,
            "object": model_info.object,
            "created": model_info.created,
            "owned_by": model_info.owned_by,
        }

    return router
