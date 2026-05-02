import re

with open('services/llm_service.py', 'r', encoding='utf-8') as f:
    content = f.read()

init_replacement = """    def __init__(self):
        \"\"\"Initialize Groq async client\"\"\"
        try:
            self.model_name = settings.groq_llm_model
            self.api_keys = settings.all_groq_keys
            if not self.api_keys:
                self.api_keys = [settings.groq_api_key]
            self.current_key_idx = 0
            self.client = AsyncGroq(api_key=self.api_keys[self.current_key_idx])
            logger.info(f"✅ Groq LLM service initialized — model: {self.model_name}, loaded {len(self.api_keys)} keys")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Groq LLM service: {e}")
            raise"""

chat_replacement = """    async def _chat(self, prompt: str, max_tokens: int = 2048) -> Optional[str]:
        \"\"\"Send a prompt to Groq and return the text response.\"\"\"
        attempts = 0
        max_attempts = len(self.api_keys)
        
        while attempts < max_attempts:
            try:
                resp = await self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    temperature=0.3,
                )
                return resp.choices[0].message.content
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Groq API error on key index {self.current_key_idx}: {error_msg}")
                # Check for rate limit error (429)
                if "429" in error_msg or "rate_limit_exceeded" in error_msg.lower():
                    attempts += 1
                    if attempts < max_attempts:
                        self.current_key_idx = (self.current_key_idx + 1) % len(self.api_keys)
                        logger.warning(f"Rate limit hit. Switching to Groq API key index {self.current_key_idx}")
                        self.client = AsyncGroq(api_key=self.api_keys[self.current_key_idx])
                        continue
                return None
        logger.error("All Groq API keys exhausted or failed.")
        return None"""

content = re.sub(
    r'    def __init__\(self\):\s*"""Initialize Groq async client"""\s*try:\s*self.model_name = settings.groq_llm_model\s*self.client = AsyncGroq\(api_key=settings.groq_api_key\)\s*logger.info\(f"✅ Groq LLM service initialized — model: \{self.model_name\}"\)\s*except Exception as e:\s*logger.error\(f"❌ Failed to initialize Groq LLM service: \{e\}"\)\s*raise',
    init_replacement,
    content,
    flags=re.MULTILINE
)

content = re.sub(
    r'    async def _chat\(self, prompt: str, max_tokens: int = 2048\) -> Optional\[str\]:\s*"""Send a prompt to Groq and return the text response."""\s*try:\s*resp = await self.client.chat.completions.create\(\s*model=self.model_name,\s*messages=\[\{"role": "user", "content": prompt\}\],\s*max_tokens=max_tokens,\s*temperature=0.3,\s*\)\s*return resp.choices\[0\].message.content\s*except Exception as e:\s*logger.error\(f"Groq API error: \{e\}"\)\s*return None',
    chat_replacement,
    content,
    flags=re.MULTILINE
)

with open('services/llm_service.py', 'w', encoding='utf-8') as f:
    f.write(content)
