"""
CHIMERA Server Integration Patch
Add this to chimera_server.py to enable local LLM priority
"""

# Add these imports at the top of chimera_server.py:
# from chimera_local_integration import LocalLLMClient, should_use_local

# Add to config.py or at the top:
USE_LOCAL_MODELS = True  # Enable local model priority
LOCAL_MODEL_FALLBACK = True  # Fall back to API if local fails

# Replace the _process_completion function with this version:

async def _process_completion_with_local(request: ChatCompletionRequest):
    """
    CHIMERA request pipeline with LOCAL LLM PRIORITY:
    1. Check if local models should be used
    2. Try local models first (with consensus)
    3. Fall back to API only if local fails
    4. Cache results
    """
    from .chimera_local_integration import LocalLLMClient, should_use_local
    
    messages_raw = [{"role": m.role, "content": m.content or ""} for m in request.messages]
    
    # --- Step 1: Try Local Models First ---
    if USE_LOCAL_MODELS and should_use_local():
        logger.info("🤖 Attempting local LLM processing...")
        
        try:
            async with LocalLLMClient() as local_client:
                # Try local completion with consensus
                result = await local_client.chat_completion_with_consensus(
                    messages=messages_raw,
                    max_tokens=request.max_tokens or 256,
                    temperature=request.temperature,
                    min_agreement=1,  # At least 1 model
                )
                
                if result.get("content") and not result.get("error"):
                    logger.info(f"✅ Local LLM success: {result['model']}")
                    
                    # Build OpenAI-compatible response
                    completion_id = f"chatcmpl-chimera-local-{uuid.uuid4().hex[:12]}"
                    return ChatCompletionResponse(
                        id=completion_id,
                        created=int(time.time()),
                        model=f"chimera-local/{result['model']}",
                        choices=[
                            Choice(
                                message=ChatMessage(role="assistant", content=result["content"]),
                                finish_reason="stop",
                            )
                        ],
                        usage=Usage(**result.get("usage", {})),
                    ).model_dump()
                
                elif result.get("fallback_required") and LOCAL_MODEL_FALLBACK:
                    logger.warning("⚠️ Local models failed, falling back to API")
                    # Continue to API fallback below
                
        except Exception as e:
            logger.error(f"Local LLM error: {e}")
            if not LOCAL_MODEL_FALLBACK:
                raise HTTPException(status_code=503, detail=f"Local models failed: {e}")
    
    # --- Step 2: API Fallback (Original Logic) ---
    logger.info("🌐 Using API models...")
    
    # Original API-based processing logic here
    # [Keep the existing _process_completion code for API fallback]
    
    # For now, call the original function
    return await _process_completion_original(request)


# Add this endpoint to chimera_server.py:

@app.get("/v1/local_status")
async def local_status():
    """Get status of all local LLM servers."""
    from .chimera_local_integration import LocalLLMClient, LOCAL_MODELS
    
    async with LocalLLMClient() as client:
        status = {}
        for model in LOCAL_MODELS:
            healthy = await client.check_health(model)
            status[model.name] = {
                "url": model.url,
                "healthy": healthy,
                "priority": model.priority,
            }
    
    return {
        "local_models_enabled": USE_LOCAL_MODELS,
        "api_fallback_enabled": LOCAL_MODEL_FALLBACK,
        "models": status,
        "healthy_count": sum(1 for s in status.values() if s["healthy"]),
    }


# Add startup check in startup_banner:

@app.on_event("startup")
async def startup_banner():
    # ... existing banner code ...
    
    # Check local models
    from .chimera_local_integration import LocalLLMClient
    try:
        async with LocalLLMClient() as client:
            healthy = await client.get_healthy_models()
            logger.info(f"🤖 Local models: {len(healthy)} healthy")
            for m in healthy:
                logger.info(f"   ✅ {m.name} @ {m.url}")
    except Exception as e:
        logger.warning(f"🤖 Local models check failed: {e}")
