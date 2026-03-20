import re

file_path = r'D:\appforge-main\infrastructure\clawd-hybrid-rtx\src\openrouter_client.py'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# The new function implementation
new_function = r'''async def query_all_models(
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int | None = None,
    models: list[str] | None = None,
) -> list[ModelResponse]:
    """Query all configured models in parallel and return responses.

    Uses First-Good-Answer-Wins strategy with a 3000ms grace period.
    """
    target_models = models or MODELS

    # --- 1. Filter to healthy primary models ---
    healthy = get_healthy_models(target_models)

    if not healthy:
        logger.warning(
            "All %d primary models are in cooldown — trying fallback models",
            len(target_models),
        )
        healthy = get_healthy_models(FALLBACK_MODELS)

        if not healthy:
            logger.warning(
                "All fallback models also in cooldown — resetting oldest cooldowns",
            )
            _reset_oldest_cooldowns(target_models)
            _reset_oldest_cooldowns(FALLBACK_MODELS)
            healthy = get_healthy_models(target_models + FALLBACK_MODELS)

            if not healthy:
                healthy = target_models

    logger.info(
        "Querying %d healthy model(s): %s",
        len(healthy),
        ", ".join(m.split("/")[-1] for m in healthy),
    )

    results: list[ModelResponse] = []
    
    # --- Async First-Good-Wins with Grace Period ---
    async with httpx.AsyncClient() as client:
        tasks = []
        for model in healthy:
            # We wrap query_single_model in a task
            task = asyncio.create_task(
                query_single_model(client, model, messages, temperature, max_tokens)
            )
            task.set_name(model)
            tasks.append(task)
            
        if not tasks:
             return [ModelResponse(model="system", content="", error="No models available")]

        pending = set(tasks)
        finished_success = False
        first_success_time = 0.0
        GRACE_PERIOD = 3.0 # seconds
        
        while pending:
            # Calculate timeout
            timeout = None
            if finished_success:
                elapsed = time.monotonic() - first_success_time
                remaining = GRACE_PERIOD - elapsed
                if remaining <= 0:
                    logger.info("Grace period expired, cancelling remaining tasks")
                    break
                timeout = remaining
                
            done, pending = await asyncio.wait(
                pending, 
                return_when=asyncio.FIRST_COMPLETED,
                timeout=timeout
            )
            
            if not done and finished_success:
                # Timeout hit during grace period
                logger.info("Grace period expired (timeout), cancelling remaining tasks")
                break
                
            for task in done:
                try:
                    resp = task.result()
                    results.append(resp)
                    
                    # Check for success
                    if resp.content and not resp.error:
                        if not finished_success:
                            finished_success = True
                            first_success_time = time.monotonic()
                            logger.info(f"First success from {resp.model}, starting {GRACE_PERIOD}s grace period")
                        
                except Exception as e:
                    logger.error(f"Task exception: {e}")
                    
        # Cancel remaining
        for task in pending:
            task.cancel()

    # Check if we have any successes
    successful = [r for r in results if r.error is None and r.content]
    
    # --- Fallback Logic if everything failed ---
    if not successful:
        logger.warning("All primary models failed in consensus — trying fallback models")
        fallback_candidates = get_healthy_models(FALLBACK_MODELS)
        already_tried = set(healthy)
        fallback_candidates = [m for m in fallback_candidates if m not in already_tried]

        if fallback_candidates:
            # Recurse for fallbacks (simple sequential for now)
            async with httpx.AsyncClient() as client:
                 fb_tasks = [
                    query_single_model(
                        client, model, messages, temperature, max_tokens
                    )
                    for model in fallback_candidates
                ]
                 fb_responses = await asyncio.gather(*fb_tasks, return_exceptions=True)
                 
                 for i, resp in enumerate(fb_responses):
                    if isinstance(resp, Exception):
                        results.append(ModelResponse(
                            model=fallback_candidates[i],
                            content="",
                            error=str(resp),
                        ))
                    else:
                        results.append(resp)

    # --- Guarantee at least one response ---
    if not results:
        results.append(ModelResponse(
            model="system",
            content="",
            error="No models available. Check OPENROUTER_API_KEY and network connectivity.",
        ))

    return results'''

# Regex to replace the entire function
# Matches from 'async def query_all_models' to the end of the file logic for that function
# Assuming it's the last big function or we match carefully
pattern = re.compile(r'async def query_all_models\(.+?return results', re.DOTALL)

if pattern.search(content):
    new_content = pattern.sub(new_function, content)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("Successfully updated query_all_models")
else:
    print("Could not find query_all_models function")